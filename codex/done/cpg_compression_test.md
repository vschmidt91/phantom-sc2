# CPG Compression Test Notebook

## User Request
Create `notebook/cpg_compression_test.ipynb` to compare compression algorithms on `phantom/common/distribute/cpg/*.pyd` in terms of compression ratio and (de)compression speed.

## Implemented
- Added notebook with auto-discovery of `.pyd` binaries.
- Benchmarks stdlib codecs: `zlib` (levels 1/6/9), `gzip` (level 6), `bz2` (level 9), `lzma` (preset 6).
- Optionally benchmarks `brotli`, `zstandard`, and `lz4` when installed.
- Verifies round-trip integrity for each codec/file.
- Reports per-file best ratio, weighted aggregate table, and top-3 rankings by ratio/compression/decompression speed.

## Follow-up (max compression)
- Verified compression ratios on current `.pyd` set: `lzma` is best; `preset=9|PRESET_EXTREME` slightly improves over `preset=6`.
- Updated `scripts/compile_cvxpy.py` to create `cpg.tar.xz` via `tarfile.open(..., mode='w:xz', preset=9|lzma.PRESET_EXTREME)` instead of `shutil.make_archive('xztar')` to enforce max xz compression.
