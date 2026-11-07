param(
  [Parameter(Mandatory = $true)][string]$JsonFile,
  [Parameter(Mandatory = $true)][string]$OutFile,
  [int]$Rate = 0
)

$ErrorActionPreference = "Stop"
try {
  Add-Type -AssemblyName System.Speech
  $raw = [System.IO.File]::ReadAllText($JsonFile, [System.Text.Encoding]::UTF8)
  $segments = ConvertFrom-Json $raw
  $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
  $builder = New-Object System.Speech.Synthesis.PromptBuilder
  foreach ($segment in $segments) {
    $text = [string]$segment.text
    $pause = [double]$segment.pause
    if ($text.Trim().Length -eq 0) {
      if ($pause -gt 0) { $builder.AppendBreak([TimeSpan]::FromSeconds($pause)) }
      continue
    }
    $voice = [string]$segment.voice
    $started = $false
    if ($voice -and $voice.Trim().Length -gt 0) {
      try {
        $builder.StartVoice($voice)
        $started = $true
      }
      catch { }
    }
    $builder.AppendText($text)
    if ($started) { $builder.EndVoice() }
    if ($pause -gt 0) {
      $builder.AppendBreak([TimeSpan]::FromSeconds($pause))
    }
  }
  $synth.SetOutputToWaveFile($OutFile)
  $synth.Speak($builder)
  $synth.Dispose()
  exit 0
}
catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}
