# Changelog

All notable changes to WallStitch are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Wikimedia Commons as a second wallpaper source: freely licensed panoramic
  photos, many of them true 32:9. Pick it from the new Source dropdown in the
  picker and the slideshow import, or use `--source commons` on the command
  line. Only images within 2% of your desktop's shape are shown, so nothing
  is visibly cropped. Hover a thumbnail for its author and license.

### Changed
- "Browse Wallhaven…" is now "Find Wallpapers…".

## [0.2.0] - 2026-11-19

### Added
- Search and filters for wallhaven.cc: keywords (including `+tag -tag`),
  a category dropdown (General, Anime, People or any mix), sort order (random, relevance, most
  favorited, top this year, most viewed, newest, hot), color, and a "Match my
  screen shape" toggle. Shared by the picker and the slideshow import, and
  remembered between sessions.
- The picker pages through results with More (or Shuffle for random order)
  and says when few images match your screen shape.
- CLI: `--search`, `--category`, `--sort`, `--color` and `--any-shape` for
  `fetch` and `slideshow start --fetch`.

### Changed
- "Random Wallpapers…" is now "Browse Wallhaven…".

## [0.1.1] - 2026-11-02

### Fixed
- Flatpak: WallStitch crashed on start after the KDE 6.11 runtime moved to
  Qt 6.11.3 ("undefined symbol ... Qt_6_PRIVATE_API"). Rebuilt against the
  matching PySide6 6.11.3.

## [0.1.0] - 2026-10-20

First release.

### Added
- Span one wallpaper across any monitor layout on KDE Plasma 6 (multi-monitor,
  ultrawide, stacked/offset, mixed resolutions, HiDPI).
- Visual editor with drag-to-pan, scroll-to-zoom and bezel compensation.
- Random wallpapers from wallhaven.cc sized for your desktop.
- Synced spanning slideshow of up to 50 images, run by a background agent that
  starts at login and re-fits the image when monitors change.
- Preview and frame each slideshow image individually; framing is saved per
  image.
- Restore the wallpaper you had before WallStitch.
- Packages: Flatpak (any distro) and .deb (Ubuntu 25.10+).
- Command-line interface: `screens`, `set`, `reapply`, `restore`, `fetch`,
  `slideshow start|stop|next|status`.

[0.2.0]: https://github.com/travisinpdx/wallstitch/releases/tag/v0.2.0
[0.1.1]: https://github.com/travisinpdx/wallstitch/releases/tag/v0.1.1
[0.1.0]: https://github.com/travisinpdx/wallstitch/releases/tag/v0.1.0
