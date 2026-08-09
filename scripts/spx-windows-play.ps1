Import-Module AudioDeviceCmdlets

$speaker = Get-AudioDevice -List | Where-Object {
    $_.Type -eq 'Playback' -and $_.Name -match 'Aqstic|Speakers'
} | Select-Object -First 1

if ($speaker) {
    Set-AudioDevice -ID $speaker.ID
}

Set-AudioDevice -PlaybackVolume 100
Set-AudioDevice -PlaybackMute 0

@(
    Get-AudioDevice -Playback
    "Volume=$(Get-AudioDevice -PlaybackVolume)"
    "Mute=$(Get-AudioDevice -PlaybackMute)"
) | Out-File C:\Users\D\spx-audio-state.txt

$player = New-Object System.Media.SoundPlayer 'C:\Users\D\spx-tone.wav'
$player.Load()
'SoundPlayer=loaded' | Out-File C:\Users\D\spx-play-state.txt
$player.PlaySync()
'SoundPlayer=completed' | Out-File C:\Users\D\spx-play-state.txt
