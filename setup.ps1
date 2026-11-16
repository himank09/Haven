# One-time setup for running Haven from source.
# Everything goes into this folder (.venv), so deleting the folder removes it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# The desktop window (pywebview -> pythonnet) supports Python 3.10 - 3.13
function Test-Py($exe) {
    try {
        $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        return ($LASTEXITCODE -eq 0 -and $v -in @("3.10", "3.11", "3.12", "3.13"))
    } catch { return $false }
}

function Find-Python {
    foreach ($ver in @("3.12", "3.13", "3.11", "3.10")) {
        try {
            $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
        } catch {}
    }
    try {
        $exe = & python -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Py $exe.Trim())) { return $exe.Trim() }
    } catch {}
    return $null
}

Write-Host "`n== Haven setup ==" -ForegroundColor Cyan

# Re-use an existing environment if its Python version is supported
if ((Test-Path ".venv\Scripts\python.exe") -and -not (Test-Py ".venv\Scripts\python.exe")) {
    Write-Host "Existing .venv uses an unsupported Python version - recreating it."
    Remove-Item ".venv" -Recurse -Force
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $py = Find-Python
    if (-not $py) {
        Write-Host "Installing Python 3.12 (free, via winget)..." -ForegroundColor Yellow
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $py = Find-Python
        if (-not $py) { Write-Host "Python installed. Close this window and run setup.bat again." -ForegroundColor Red; exit 1 }
    }
    Write-Host "Using $(& $py --version) at $py"
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create the environment." -ForegroundColor Red; exit 1 }
}

Write-Host "Installing components (about 150 MB, one time)..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "Install failed - check your internet and run setup again." -ForegroundColor Red; exit 1 }

# Desktop + Start menu shortcuts (no console window)
$target = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
foreach ($old in @("My Desk.lnk")) {   # shortcuts from earlier versions
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
        Remove-Item (Join-Path $dir $old) -ErrorAction SilentlyContinue
    }
}
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Haven.lnk") -ErrorAction SilentlyContinue
# Start menu name includes "PDF" so Windows search finds it for "haven" or "pdf"
foreach ($pair in @(@([Environment]::GetFolderPath("Desktop"), "Haven.lnk"), @([Environment]::GetFolderPath("Programs"), "Haven - PDF Tools.lnk"))) {
    $s = $shell.CreateShortcut((Join-Path $pair[0] $pair[1]))
    $s.TargetPath = $target
    $s.Arguments = '"' + (Join-Path $PSScriptRoot "app.py") + '"'
    $s.WorkingDirectory = $PSScriptRoot
    $s.IconLocation = (Join-Path $PSScriptRoot "assets\icon.ico")
    $s.Description = "Compress, merge, split and convert PDFs and other files, plus local AI chat"
    $s.Save()
}

Write-Host "`nDone! Open 'Haven' from your desktop or Start menu." -ForegroundColor Green
Write-Host "Optional extras (stronger compression, PowerPoint/Word -> PDF):" -ForegroundColor Gray
Write-Host "  Ghostscript: https://ghostscript.com/releases/gsdnld.html (64-bit installer)" -ForegroundColor Gray
Write-Host "  winget install -e --id TheDocumentFoundation.LibreOffice" -ForegroundColor Gray
