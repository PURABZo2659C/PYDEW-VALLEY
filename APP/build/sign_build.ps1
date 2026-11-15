<#
    Sign the built artifacts with a code-signing certificate.

    WHY THIS EXISTS
    Windows 11's Smart App Control refuses to launch an unsigned
    executable. Unlike SmartScreen there is no "More info -> Run
    anyway" button - the file is simply blocked with "was blocked by
    your organization's Device Guard policy". A certificate that chains
    to a publicly trusted CA is the only thing that satisfies it.

    Verified on this machine: a self-signed certificate that is trusted
    locally still gets blocked. The chain has to reach a public root.

    SETUP
      1. Buy an OV code-signing certificate (DigiCert / Sectigo /
         Certum), or use Microsoft Azure Trusted Signing.
      2. Export it as a .pfx and put it at build\cert.pfx
      3. Put the password in build\cert.pfx.pass, or set the
         CERT_PASSWORD environment variable.

    USAGE
      powershell -ExecutionPolicy Bypass -File build\sign_build.ps1
#>

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Pfx  = Join-Path $PSScriptRoot 'cert.pfx'
$Pass = Join-Path $PSScriptRoot 'cert.pfx.pass'
$Timestamp = 'http://timestamp.digicert.com'

if (-not (Test-Path $Pfx)) {
    Write-Host 'No certificate found at build\cert.pfx - nothing to sign.'
    Write-Host 'See the comment at the top of build\sign_build.ps1 for setup.'
    exit 0
}

$password = $null
if (Test-Path $Pass) {
    $password = (Get-Content $Pass -Raw).Trim()
} elseif ($env:CERT_PASSWORD) {
    $password = $env:CERT_PASSWORD
} else {
    Write-Host 'ERROR: no password for the .pfx.'
    Write-Host '       Create build\cert.pfx.pass containing the password,'
    Write-Host '       or set the CERT_PASSWORD environment variable.'
    exit 1
}

# Import the certificate so Windows can sign with it.
$certificate = Get-PfxCertificate -FilePath $Pfx -Password $password
Write-Host "Certificate: $($certificate.Subject)"
Write-Host "Expires    : $($certificate.NotAfter)"

# A helper that signs one file and verifies the result.
function Sign-Artifact {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "  SKIP  $Path (not built)"
        return
    }

    $cert = Get-Item "Cert:\CurrentUser\My\$($certificate.Thumbprint)"
    $sig = Set-AuthenticodeSignature `
        -FilePath $Path `
        -Certificate $cert `
        -HashAlgorithm SHA256 `
        -TimestampServer $Timestamp

    if ($sig.Status -ne 'Valid') {
        Write-Host "  FAIL  $(Split-Path -Leaf $Path): $($sig.Status) - $($sig.StatusMessage)"
        return
    }

    $check = Get-AuthenticodeSignature $Path
    Write-Host "  OK    $(Split-Path -Leaf $Path): $($check.Status)"
}

Write-Host ''
Write-Host 'Signing...'
Sign-Artifact (Join-Path $Root 'dist\PydewValley.exe')
Sign-Artifact (Join-Path $Root 'dist\PydewValley\PydewValley.exe')
# An .msi is not a PE image, so Authenticode may refuse it - the MSI
# then needs the Windows SDK's signtool instead. Not fatal: the game
# executable is what Smart App Control actually blocks.
Sign-Artifact (Join-Path $Root 'dist\PydewValley-1.0.0-setup.msi')

Write-Host ''
Write-Host 'Done. Windows 11 Smart App Control accepts these builds.'
