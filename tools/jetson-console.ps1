<#
USB serial console for the Jetson. Uses only the Windows/.NET serial API.
The Jetson handles login and password entry. This script stores no credentials.
Exit the console with Ctrl+]. Ctrl+C is sent to the Jetson.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^COM[0-9]+$')]
    [string]$Port = 'COM3',
    [ValidateRange(1200, 3000000)]
    [int]$Baud = 115200,
    [switch]$Probe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Probe -and [Console]::IsInputRedirected) {
    throw 'Run this script from an interactive PowerShell terminal, or use -Probe.'
}

$jetsonSerial = [System.IO.Ports.SerialPort]::new(
    $Port, $Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One
)
$jetsonSerial.Handshake = [System.IO.Ports.Handshake]::None
$jetsonSerial.Encoding = [System.Text.Encoding]::UTF8
$jetsonSerial.DtrEnable = $false
$jetsonSerial.RtsEnable = $false
$jetsonSerial.ReadTimeout = 500
$jetsonSerial.WriteTimeout = 1000
$previousControlC = $null

try {
    $jetsonSerial.Open()
    if ($Probe) {
        $initial = $jetsonSerial.ReadExisting()
        $jetsonSerial.Write("`r")
        Start-Sleep -Milliseconds 600
        Write-Output ($initial + $jetsonSerial.ReadExisting())
        return
    }

    Write-Host "Jetson serial console: $Port, $Baud baud. Exit: Ctrl+]." -ForegroundColor Cyan
    Write-Host 'Log in on the Jetson when prompted. Password entry is handled by the Jetson.'
    $previousControlC = [Console]::TreatControlCAsInput
    [Console]::TreatControlCAsInput = $true
    $jetsonSerial.Write("`r")
    while ($true) {
        $received = $jetsonSerial.ReadExisting()
        if ($received) { [Console]::Write($received) }
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ([int]$key.KeyChar -eq 29) { break }
            $send = switch ($key.Key) {
                'Enter' { "`r" }
                'Backspace' { [string][char]127 }
                'UpArrow' { ([string][char]27) + '[A' }
                'DownArrow' { ([string][char]27) + '[B' }
                'RightArrow' { ([string][char]27) + '[C' }
                'LeftArrow' { ([string][char]27) + '[D' }
                'Home' { ([string][char]27) + '[H' }
                'End' { ([string][char]27) + '[F' }
                'Delete' { ([string][char]27) + '[3~' }
                default { if ([int]$key.KeyChar -ne 0) { [string]$key.KeyChar } }
            }
            if ($send) { $jetsonSerial.Write([string]$send) }
        }
        Start-Sleep -Milliseconds 20
    }
}
finally {
    if ($null -ne $previousControlC) { [Console]::TreatControlCAsInput = $previousControlC }
    if ($jetsonSerial.IsOpen) { $jetsonSerial.Close() }
    $jetsonSerial.Dispose()
}
