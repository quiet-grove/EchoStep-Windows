param(
  [Parameter(Mandatory = $true)][string]$TextFile,
  [Parameter(Mandatory = $true)][string]$OutFile,
  [int]$Rate = 0,
  [string]$Voice = ""
)

$ErrorActionPreference = "Stop"
try {
  Add-Type -AssemblyName System.Speech
  $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
  $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
  if ($Voice -and $Voice.Trim().Length -gt 0) {
    try { $synth.SelectVoice($Voice) } catch { }
  }
  else {
    $english = $synth.GetInstalledVoices() | Where-Object {
      $_.Enabled -and $_.VoiceInfo.Culture.Name -like "en-*"
    } | Select-Object -First 1
    if ($english) { try { $synth.SelectVoice($english.VoiceInfo.Name) } catch { } }
  }
  $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
  $synth.SetOutputToWaveFile($OutFile)
  $synth.Speak($text)
  $synth.Dispose()
  exit 0
}
catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}
