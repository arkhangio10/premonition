<#
Controlled recovery for this Jetson's two Windows USB network interfaces.
Disables NCM temporarily, then restarts RNDIS. No firewall or VM bindings change.
Run in an Administrator PowerShell. -Restore re-enables the NCM adapter.
-WhatIf previews the operation without elevation or changes.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$NcmAdapter = 'Ethernet 3',
    [string]$RndisAdapter = 'Ethernet 4',
    [switch]$Restore
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -and -not $WhatIfPreference) {
    throw 'Open PowerShell as Administrator, then run this script again. No changes were made.'
}

$ncm = Get-NetAdapter -Name $NcmAdapter
$rndis = Get-NetAdapter -Name $RndisAdapter
if ($ncm.InterfaceDescription -notlike '*UsbNcm*' -or $rndis.InterfaceDescription -notlike '*Remote NDIS Compatible*') {
    throw 'Adapter descriptions do not match the inspected Jetson USB interfaces. No changes were made.'
}
foreach ($adapter in @($ncm, $rndis)) {
    if ($adapter.PnPDeviceID -notmatch '^USB\\VID_0955&PID_7020&') {
        throw "Adapter $($adapter.Name) does not match the inspected NVIDIA USB device. No changes were made."
    }
}

$operation = if ($Restore) { "Enable NCM on $NcmAdapter and restart RNDIS on $RndisAdapter" } else { "Disable NCM on $NcmAdapter and restart RNDIS on $RndisAdapter" }
if (-not $PSCmdlet.ShouldProcess('Jetson USB network adapters', $operation)) { return }

if ($Restore) {
    Enable-NetAdapter -Name $NcmAdapter -Confirm:$false
} else {
    Disable-NetAdapter -Name $NcmAdapter -Confirm:$false
}
Restart-NetAdapter -Name $RndisAdapter -Confirm:$false
Start-Sleep -Seconds 3

$client = [Net.Sockets.TcpClient]::new()
try {
    $attempt = $client.ConnectAsync('192.168.55.1', 22)
    if ($attempt.Wait(5000) -and $client.Connected) {
        Write-Host 'SSH is reachable at 192.168.55.1:22.' -ForegroundColor Green
    } else {
        Write-Host 'SSH still does not respond. Report this result; further diagnosis is needed.' -ForegroundColor Yellow
    }
} catch {
    Write-Host 'SSH still does not respond. Report this result; further diagnosis is needed.' -ForegroundColor Yellow
} finally {
    $client.Dispose()
}
if (-not $Restore) {
    Write-Host 'NCM remains disabled for this test. Use this script with -Restore to re-enable it.'
}
