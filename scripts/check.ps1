[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string] $Command,

        [Parameter(ValueFromRemainingArguments)]
        [string[]] $Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Command $($Arguments -join ' ')' failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10 or later is required."
}

if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked py -3 -m venv $venv
    }
    else {
        Invoke-Checked python -m venv $venv
    }
}

Invoke-Checked $python -m pip install --quiet --upgrade pip
Invoke-Checked $python -m pip install --quiet `
    -r (Join-Path $root "src\adaptive-card-agent\requirements.txt") `
    -r (Join-Path $root "requirements-dev.txt")

Invoke-Checked $python -m compileall -q (Join-Path $root "src\adaptive-card-agent")
Invoke-Checked $python -m ruff format --check `
    (Join-Path $root "src\adaptive-card-agent") `
    (Join-Path $root "tests")
Invoke-Checked $python -m ruff check `
    (Join-Path $root "src\adaptive-card-agent") `
    (Join-Path $root "tests")
Invoke-Checked $python -m pyright
Invoke-Checked $python -m pytest -q (Join-Path $root "tests")
