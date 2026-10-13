# Build "dist\Cytosol Viewer\Cytosol Viewer.exe" on Windows and zip it.
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
# Uses $env:PYTHON if set, otherwise "py -3.12".  Output: dist\CytosolViewer-Windows.zip
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

$zip = 'dist\CytosolViewer-Windows.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path 'dist\Cytosol Viewer' -DestinationPath $zip
Write-Host "Built: $(Resolve-Path $exe)"
Write-Host "Zip:   $(Resolve-Path $zip)"
