param(
    [Parameter(Mandatory = $true)] [string]$OutputRoot,
    [datetime]$CutoffExclusive = [datetime]'2026-09-25',
    [switch]$Execute
)

$rootItem = Get-Item -LiteralPath $OutputRoot -ErrorAction Stop
if (-not $rootItem.PSIsContainer) { throw "OutputRoot is not a directory" }
$root = $rootItem.FullName.TrimEnd('\')
$archive = [IO.Path]::GetFullPath((Join-Path $root '_archive\through-2026-09-24'))
$rootPrefix = $root + '\'
$archivePrefix = $archive + '\'
if (-not $archive.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Archive escaped OutputRoot: $archive"
}

function New-Entry([IO.DirectoryInfo]$Directory, [string]$Group) {
    if (($Directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to move a reparse point: $($Directory.FullName)"
    }
    $source = [IO.Path]::GetFullPath($Directory.FullName)
    $target = [IO.Path]::GetFullPath((Join-Path (Join-Path $archive $Group) $Directory.Name))
    if (-not $source.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $source.StartsWith($archivePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $target.StartsWith($archivePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Move path escaped the expected tree: $source -> $target"
    }
    if (Test-Path -LiteralPath $target) { throw "Archive destination already exists: $target" }
    $files = @(Get-ChildItem -LiteralPath $source -Recurse -File -ErrorAction Stop)
    $newestFile = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $newest = if ($newestFile) { $newestFile.LastWriteTime } else { $Directory.LastWriteTime }
    if ($newest -ge $CutoffExclusive) { return $null }
    $bytes = ($files | Measure-Object Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    return [pscustomobject]@{
        from = $source
        to = $target
        newest_file = $newest.ToString('yyyy-MM-dd HH:mm:ss')
        files = $files.Count
        bytes = [long]$bytes
    }
}

$entries = [System.Collections.Generic.List[object]]::new()
foreach ($directory in (Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name)) {
    if ($directory.Name -match '^mv_director(?:-\d+)?$') {
        $entry = New-Entry $directory 'mv_director'
        if ($null -ne $entry) { $entries.Add($entry) }
    }
}
$chains = Join-Path $root 'h3_chains'
foreach ($directory in (Get-ChildItem -LiteralPath $chains -Directory | Sort-Object Name)) {
    $entry = New-Entry $directory 'h3_chains'
    if ($null -ne $entry) { $entries.Add($entry) }
}

$result = [ordered]@{
    output_root = $root
    archive_root = $archive
    cutoff_exclusive = $CutoffExclusive.ToString('yyyy-MM-dd')
    folder_count = $entries.Count
    file_count = ($entries | Measure-Object files -Sum).Sum
    bytes = ($entries | Measure-Object bytes -Sum).Sum
    entries = @($entries)
}
$reportDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\assets\research\output-archive-2026-09-25'
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$planPath = Join-Path $reportDir 'plan.json'
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $planPath -Encoding utf8
Write-Output "plan=$planPath folders=$($entries.Count) files=$($result.file_count) bytes=$($result.bytes)"
if (-not $Execute) { return }

try {
    $queue = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/queue' -TimeoutSec 5
    if ($queue.queue_running.Count -or $queue.queue_pending.Count) {
        throw "ComfyUI queue is not empty; refusing to move outputs"
    }
} catch {
    throw "Cannot prove ComfyUI queue is idle: $($_.Exception.Message)"
}
foreach ($group in @('mv_director', 'h3_chains')) {
    New-Item -ItemType Directory -Path (Join-Path $archive $group) -Force | Out-Null
}
$moved = [System.Collections.Generic.List[object]]::new()
$movedPath = Join-Path $reportDir 'moved.json'
foreach ($entry in $entries) {
    Move-Item -LiteralPath $entry.from -Destination $entry.to -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $entry.to) -or (Test-Path -LiteralPath $entry.from)) {
        throw "Move verification failed: $($entry.from) -> $($entry.to)"
    }
    $moved.Add($entry)
    $result.entries = @($moved)
    $result.folder_count = $moved.Count
    $result.file_count = ($moved | Measure-Object files -Sum).Sum
    $result.bytes = ($moved | Measure-Object bytes -Sum).Sum
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $movedPath -Encoding utf8
}
$archiveLines = [System.Collections.Generic.List[string]]::new()
$archiveLines.Add('# 2026-09-24以前のComfyUI出力')
$archiveLines.Add('')
$archiveLines.Add("移動日時: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$archiveLines.Add("元ディレクトリ: $root")
$archiveLines.Add('保存済みPlan・EMD・動画・checkpointは削除せず、同じCドライブ内で移動した。旧絶対パスを参照する文書やWFは新パスへ読み替える。')
$archiveLines.Add('')
$archiveLines.Add('| 旧パス（outputからの相対） | 移動先 | ファイル数 |')
$archiveLines.Add('| --- | --- | ---: |')
foreach ($entry in $moved) {
    $oldRelative = $entry.from.Substring($rootPrefix.Length).Replace('\', '/')
    $newRelative = $entry.to.Substring($archivePrefix.Length).Replace('\', '/')
    $archiveLines.Add("| $oldRelative | [$newRelative](<$newRelative/>) | $($entry.files) |")
}
$archiveLines | Set-Content -LiteralPath (Join-Path $archive '_INDEX.md') -Encoding utf8
Write-Output "moved=$movedPath folders=$($moved.Count)"
