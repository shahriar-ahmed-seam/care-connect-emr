# Brand assets — drop files here

Place the final brand assets in this folder using these exact filenames so the
app picks them up without code changes. Until provided, the UI uses an inline
SVG logo placeholder.

| Filename                 | Used for                                  | Format / size            |
|--------------------------|-------------------------------------------|--------------------------|
| `logo.svg`               | Header wordmark + mark                    | SVG (transparent)        |
| `logo-mark.svg`          | Square icon (favicon, compact spots)      | SVG, 1:1                 |
| `icon.png`               | Favicon / PWA icon                        | PNG, 512×512             |
| `hero.webp`              | Landing-page hero image                   | WebP, ≥ 1920×1080        |
| `og-image.png`           | Social share preview (optional)           | PNG, 1200×630            |
| `clinic-logo.png`        | Logo embedded in the prescription PDF     | PNG, ~600×200, on white  |

Reference in code:
- `<img src="/brand/hero.webp" .../>` (anything in `public/` is served from `/`).
- For the PDF logo, copy `clinic-logo.png` to `backend/app/assets/clinic-logo.png`
  and it will be embedded automatically (see that folder's README).
