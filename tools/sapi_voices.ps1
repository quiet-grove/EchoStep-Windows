$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() | ForEach-Object {
  if ($_.Enabled) {
    Write-Output ($_.VoiceInfo.Name + "|" + $_.VoiceInfo.Culture + "|" + $_.VoiceInfo.Gender)
  }
}
$synth.Dispose()
