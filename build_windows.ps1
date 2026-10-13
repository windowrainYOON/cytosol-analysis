# Build "dist\Cytosol Viewer\Cytosol Viewer.exe" on Windows and zip it.
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
# Uses $env:PYTHON if set, otherwise "py -3.12".
# Output: dist\CytosolViewer-<version>-<commit>-Windows.zip (version from cytosol\version.py)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv-win)) {
    if ($env:PYTHON) { & $env:PYTHON -m venv .venv-win } else { py -3.12 -m venv .venv-win }
    if ($LASTEXITCODE -ne 0) { throw 'could not create .venv-win' }
}
$py = '.venv-win\Scripts\python.exe'
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

& $py -m PyInstaller --noconfirm --clean cytosol_viewer_win.spec
if ($LASTEXITCODE -ne 0) { throw 'pyinstaller failed' }

$exe = 'dist\Cytosol Viewer\Cytosol Viewer.exe'
# smoke test of the built exe (windowed app: wait for it explicitly)
$p = Start-Process -FilePath $exe -ArgumentList '--selftest', 'dist\selftest' -Wait -PassThru
Get-Content 'dist\selftest\selftest.log'
if ($p.ExitCode -ne 0) { throw "selftest failed ($($p.ExitCode))" }

$ver = ([regex]::Match((Get-Content cytosol\version.py -Raw), "__version__ = '(.+)'")).Groups[1].Value
$sha = (git rev-parse --short=7 HEAD 2>$null)
if (-not $sha) { $sha = 'nogit' }
$name = "CytosolViewer-$ver-$sha-Windows"
if ($env:GITHUB_ENV) { "BUILD_NAME=$name" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8 }

Remove-Item 'dist\CytosolViewer-*-Windows.zip' -ErrorAction SilentlyContinue
$zip = "dist\$name.zip"
Compress-Archive -Path 'dist\Cytosol Viewer' -DestinationPath $zip
Write-Host "Built: $(Resolve-Path $exe)"
Write-Host "Zip:   $(Resolve-Path $zip)"
