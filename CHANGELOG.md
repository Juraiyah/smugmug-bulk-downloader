# Changelog

## [1.0.0] - 2026-01-15
### Added
- Recursive folder and photo counting across entire SmugMug account
- Bulk download of original images + full metadata (titles/tags/descriptions for photos/galleries)
- Pre/post validation via counts + logging
- Resume-safe downloads (checksum-based skip)
- Comprehensive README with uv setup and OAuth guide

## [Unreleased]
### Planned (community contributions welcome)
- Support for **video files** in galleries
- Handling of **password-protected/private galleries**
- Export to archival formats (e.g. ZIP per folder)
- Windows/Linux CI testing

### Known limitations (won't block core use)
- Password-protected galleries: not tested (may skip or error)
- Videos: currently ignored (images only)
- Rate limiting: basic retry logic (may need tuning for 100k+ accounts)

**This is a focused export tool. Bug reports/fixes welcome via Issues.**
