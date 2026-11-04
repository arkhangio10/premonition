<# Local, interactive credential setup. Never prints or passes the API key as a command argument. #>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Console]::IsInputRedirected) { throw 'Run this script in an interactive PowerShell terminal.' }
$projectDirectory = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectDirectory '.env'
$secret = Read-Host 'Meta MODEL_API_KEY' -AsSecureString
$secretPointer = [IntPtr]::Zero
try {
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $keyValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer).Trim()
    if (-not $keyValue -or $keyValue.Contains("`n") -or $keyValue.Contains("`r")) {
        throw 'Enter one non-empty API key. The configuration was not changed.'
    }
    $existing = if (Test-Path -LiteralPath $envFile) { [IO.File]::ReadAllLines($envFile) } else { @() }
    $updated = [Collections.Generic.List[string]]::new()
    $replaced = $false
    foreach ($line in $existing) {
        if ($line -match '^\s*MODEL_API_KEY\s*=') {
            if (-not $replaced) { $updated.Add('MODEL_API_KEY=' + $keyValue); $replaced=$true }
        } else { $updated.Add($line) }
    }
    if (-not $replaced) { $updated.Add('MODEL_API_KEY=' + $keyValue) }
    [IO.File]::WriteAllLines($envFile, $updated, [Text.UTF8Encoding]::new($false))
    Write-Host 'Meta key saved locally. Restart the app to load it. No API call was made.'
} finally {
    $keyValue = $null
    if ($secretPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
    $secret.Dispose()
}
