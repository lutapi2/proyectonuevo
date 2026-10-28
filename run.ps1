$ErrorActionPreference = 'Stop'

try {
    python --version
    if ($LASTEXITCODE -ne 0) {
        throw 'Instala Python 3 desde https://www.python.org/downloads/ y vuelve a intentarlo.'
    }
}
catch {
    Write-Error 'No se encontró Python. Instala Python 3 desde https://www.python.org/downloads/.'
    exit 1
}

python (Join-Path $PSScriptRoot 'app.py')
