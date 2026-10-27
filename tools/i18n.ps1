# Update, auto-fill and compile Turkish translations in one go.
# Usage (project root):  .\tools\i18n.ps1
$ErrorActionPreference = "Stop"
$ts = "src\mediakit\assets\i18n\mediakit_tr.ts"
$qm = "src\mediakit\assets\i18n\mediakit_tr.qm"

$files = Get-ChildItem src\mediakit -Recurse -Filter *.py | ForEach-Object { $_.FullName }

Write-Host "1/3 lupdate" -ForegroundColor Yellow
uv run pyside6-lupdate $files -no-obsolete -ts $ts
if ($LASTEXITCODE -ne 0) { throw "lupdate failed" }

Write-Host "2/3 fill missing Turkish" -ForegroundColor Yellow
uv run python tools\fill_tr.py $ts
if ($LASTEXITCODE -ne 0) { throw "fill_tr failed" }

Write-Host "3/3 lrelease" -ForegroundColor Yellow
uv run pyside6-lrelease $ts -qm $qm
if ($LASTEXITCODE -ne 0) { throw "lrelease failed" }

Write-Host "Translations up to date." -ForegroundColor Green