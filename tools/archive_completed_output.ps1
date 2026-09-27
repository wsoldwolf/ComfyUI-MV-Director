param(
    [string]$OutputRoot = 'C:\Software\ComfyUI\output',
    [string]$ArchiveName = '2026-09-26',
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$archiveSourceRoot = (Resolve-Path -LiteralPath $OutputRoot).Path.TrimEnd('\')
$archiveChainsRoot = (Resolve-Path -LiteralPath (Join-Path $archiveSourceRoot 'h3_chains')).Path
if ($ArchiveName -notmatch '^\d{4}-\d{2}-\d{2}$') { throw 'ArchiveName must be a date' }
$archiveDestinationRoot = [IO.Path]::GetFullPath((Join-Path $archiveSourceRoot "_archive\$ArchiveName"))
$archiveSourcePrefix = $archiveSourceRoot + '\'
$archiveDestinationPrefix = $archiveDestinationRoot + '\'
if (-not $archiveDestinationRoot.StartsWith($archiveSourcePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Archive destination escaped output root'
}
if (Test-Path -LiteralPath $archiveDestinationRoot) { throw 'Archive already exists; no overwrite allowed' }
$protectedRuns = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$null = $protectedRuns.Add('mv_director_context_loop')
$null = $protectedRuns.Add('mv_director_context_loop.backup')
foreach ($archivePort in @(8188,8191)) {
    try { $archiveQueue = Invoke-RestMethod -Uri "http://127.0.0.1:$archivePort/queue" -TimeoutSec 5 }
    catch {
        if ($_.Exception.Message -notmatch 'refused|拒否') { throw }
        continue
    }
    foreach ($archiveJob in @($archiveQueue.queue_running) + @($archiveQueue.queue_pending)) {
        if ($null -eq $archiveJob) { continue }
        $archiveJobRunNames = @($archiveJob[2].PSObject.Properties | Where-Object {
            $_.Value.inputs.run_name
        } | ForEach-Object { $_.Value.inputs.run_name })
        if (-not $archiveJobRunNames.Count) { throw 'Active job has no identifiable run; aborting' }
        foreach ($archiveRunName in $archiveJobRunNames) { $null = $protectedRuns.Add($archiveRunName) }
    }
}

function Get-ArchiveSnapshot([string]$Directory) {
    $archiveItems = @(Get-ChildItem -LiteralPath $Directory -Recurse -Force)
    if (@($archiveItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Nested reparse point: $Directory"
    }
    return @($archiveItems | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
        [pscustomobject]@{
            path = [IO.Path]::GetRelativePath($Directory, $_.FullName)
            bytes = $_.Length
            modified_ticks = $_.LastWriteTimeUtc.Ticks
        }
    } | Sort-Object path)
}

$archivePlan = @()
foreach ($archiveDirectory in Get-ChildItem -LiteralPath $archiveChainsRoot -Directory -Force) {
    if ($archiveDirectory.Name.StartsWith('.') -or $protectedRuns.Contains($archiveDirectory.Name)) { continue }
    if ($archiveDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source is a reparse point' }
    $archiveFinalPath = Join-Path $archiveDirectory.FullName 'final'
    if (-not (Test-Path -LiteralPath $archiveFinalPath)) { continue }
    if (-not @(Get-ChildItem -LiteralPath $archiveFinalPath -File -Filter '*.mp4').Count) { continue }
    $archiveFrom = [IO.Path]::GetFullPath($archiveDirectory.FullName)
    $archiveTo = [IO.Path]::GetFullPath((Join-Path $archiveDestinationRoot "h3_chains\$($archiveDirectory.Name)"))
    if (-not $archiveFrom.StartsWith($archiveChainsRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not $archiveTo.StartsWith($archiveDestinationPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Resolved move target escaped expected directories'
    }
    $archiveSnapshot = @(Get-ArchiveSnapshot $archiveFrom)
    $archivePlan += [pscustomobject]@{
        from = $archiveFrom; to = $archiveTo
        files = $archiveSnapshot.Count
        bytes = [long](($archiveSnapshot | Measure-Object bytes -Sum).Sum)
        snapshot = $archiveSnapshot
    }
}
$archiveSummary = [ordered]@{
    created_at = (Get-Date).ToString('o')
    folders = $archivePlan.Count
    files = ($archivePlan | Measure-Object files -Sum).Sum
    bytes = ($archivePlan | Measure-Object bytes -Sum).Sum
    protected_runs = @($protectedRuns)
    entries = @($archivePlan | Select-Object from,to,files,bytes)
}
$archiveSummary | ConvertTo-Json -Depth 4
if (-not $Execute) { return }
if (-not $archivePlan.Count) { return }
New-Item -ItemType Directory -Path (Join-Path $archiveDestinationRoot 'h3_chains') | Out-Null
$archiveJournalPath = Join-Path $archiveDestinationRoot 'moves.json'
$archiveSummary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $archiveDestinationRoot 'plan.json') -Encoding utf8
$archiveMoved = @()
foreach ($archiveEntry in $archivePlan) {
    if (Test-Path -LiteralPath $archiveEntry.to) { throw 'Destination collision' }
    $archiveBefore = @(Get-ArchiveSnapshot $archiveEntry.from)
    if (Compare-Object $archiveEntry.snapshot $archiveBefore -Property path,bytes,modified_ticks) {
        throw "Source changed before move: $($archiveEntry.from)"
    }
    Move-Item -LiteralPath $archiveEntry.from -Destination $archiveEntry.to
    $archiveAfter = @(Get-ArchiveSnapshot $archiveEntry.to)
    $archiveMoved += $archiveEntry | Select-Object from,to,files,bytes
    ConvertTo-Json -InputObject @($archiveMoved) -Depth 4 | Set-Content -LiteralPath $archiveJournalPath -Encoding utf8
    if ((Test-Path -LiteralPath $archiveEntry.from) -or
        (Compare-Object $archiveBefore $archiveAfter -Property path,bytes,modified_ticks)) {
        throw "Move verification failed: $($archiveEntry.to)"
    }
}
$archiveIndex = @('# ComfyUI完了済み検証出力のアーカイブ', '',
    "作成日時: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", '',
    '動画、Plan、チェックポイントと付属ファイルを同じドライブ内で移動しました。削除・再圧縮はしていません。',
    '旧レポートのパスは次の対応表で読み替えてください。再開する場合はフォルダ全体を元の位置へ戻してください。', '',
    '| 旧絶対パス | アーカイブ先 |', '| --- | --- |')
foreach ($archiveEntry in $archiveMoved) {
    $archiveRelative = [IO.Path]::GetRelativePath($archiveDestinationRoot, $archiveEntry.to).Replace('\','/')
    $archiveIndex += "| $($archiveEntry.from) | [$archiveRelative](<$archiveRelative/>) |"
}
$archiveIndex | Set-Content -LiteralPath (Join-Path $archiveDestinationRoot '_INDEX.md') -Encoding utf8
Write-Output "Verified $($archiveMoved.Count) folder moves. Archive: $archiveDestinationRoot"
