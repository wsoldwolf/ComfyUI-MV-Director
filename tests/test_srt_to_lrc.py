from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from tools.srt_to_lrc import convert_file, convert_srt, main


SRT = "1\n00:00:19,111 --> 00:00:21,960\n朝霧を裂いて\n\n2\n00:01:00,320 --> 00:01:01,900\n秋を追い越して\n"


class SrtToLrcTests(unittest.TestCase):
    def test_japanese_start_times_centiseconds_and_final_newline(self):
        self.assertEqual(convert_srt(SRT), "[00:19.11]朝霧を裂いて\n[01:00.32]秋を追い越して\n")

    def test_millisecond_precision(self):
        self.assertEqual(convert_srt(SRT, precision=3), "[00:19.111]朝霧を裂いて\n[01:00.320]秋を追い越して\n")

    def test_bom_crlf_multiline_and_whitespace_between_cues(self):
        source = '\ufeff1\r\n00:00:00,999 --> 00:00:02,000\r\nFirst\r\n Second \r\n \r\n\t\r\n2\r\n00:00:02,000 --> 00:00:03,000\r\nNext'
        self.assertEqual(convert_srt(source), '[00:00.99]First Second\n[00:02.00]Next\n')

    def test_hours_convert_to_total_minutes(self):
        self.assertEqual(convert_srt('1\n01:02:03,456 --> 01:02:04,000\n歌う'), '[62:03.45]歌う\n')

    def test_timestamp_first_dot_fraction_and_position_metadata(self):
        self.assertEqual(convert_srt('00:00:00.000 --> 00:00:01.000 X1:0 X2:100 Y1:0 Y2:100\nSong'), '[00:00.00]Song\n')

    def test_text_and_overlapping_cues_are_not_rewritten_or_sorted(self):
        source = '1\n00:00:02,000 --> 00:00:04,000\n<i>Song</i>\n\n2\n00:00:01,000 --> 00:00:03,000\nOther'
        self.assertEqual(convert_srt(source), '[00:02.00]<i>Song</i>\n[00:01.00]Other\n')

    def test_invalid_inputs_are_rejected(self):
        for source in ('', 'plain lyrics', '1', '1\n00:00:00,000 --> 00:00:01,000',
                       '1\n00:60:00,000 --> 01:01:00,000\nSong',
                       '1\n00:00:60,000 --> 00:01:01,000\nSong',
                       '1\n00:00:02,000 --> 00:00:01,000\nSong'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                convert_srt(source)
        with self.assertRaises(ValueError):
            convert_srt(SRT, precision=4)

    def test_file_output_accepts_comfy_txt_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'lyrics.txt'
            source.write_bytes(SRT.encode('utf-8-sig'))
            original = source.read_bytes()
            destination = convert_file(source)
            self.assertEqual(destination.name, 'lyrics.lrc')
            self.assertEqual(destination.read_bytes(), convert_srt(SRT).encode('utf-8'))
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(FileExistsError):
                convert_file(source)
            convert_file(source, force=True, precision=3)
            self.assertEqual(destination.read_text(encoding='utf-8'), convert_srt(SRT, precision=3))
            with self.assertRaises(ValueError):
                convert_file(source, source, force=True)
            self.assertEqual(source.read_bytes(), original)

    def test_invalid_later_cue_does_not_create_or_replace_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'lyrics.srt'
            destination = source.with_suffix('.lrc')
            source.write_text(SRT + '\n3\nbad cue\nSong', encoding='utf-8')
            with self.assertRaises(ValueError):
                convert_file(source)
            self.assertFalse(destination.exists())
            destination.write_text('existing', encoding='utf-8')
            with self.assertRaises(ValueError):
                convert_file(source, force=True)
            self.assertEqual(destination.read_text(encoding='utf-8'), 'existing')

    def test_cli_custom_output_encoding_and_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'lyrics.srt'
            output = Path(temporary) / 'result.lrc'
            source.write_bytes(SRT.encode('cp932'))
            with redirect_stdout(StringIO()) as stdout:
                main([str(source), '-o', str(output), '--encoding', 'cp932', '--precision', '3'])
            self.assertEqual(stdout.getvalue().strip(), str(output.resolve()))
            self.assertEqual(output.read_text(encoding='utf-8'), convert_srt(SRT, precision=3))
            with redirect_stderr(StringIO()) as stderr, self.assertRaises(SystemExit) as raised:
                main([str(source), '-o', str(output)])
            self.assertEqual(raised.exception.code, 1)
            self.assertIn('--force', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
