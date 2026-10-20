---
name: transcribe
description: Transcribe audio or video (mp3, m4a, wav, mp4, mov, a recorded call, lecture, interview or meeting) into a timestamped transcript with speakers named, using local Whisper on this Mac. Use whenever the user wants a recording transcribed. Ask a few quick questions first (how many speakers, their names, topic and terms), then run it.
---

# Transcribing a recording

The `transcribe` tool (the `ocr` MCP server, or the `transcribe` command in a shell) runs Whisper and
speaker separation offline on this Mac. An hour of audio takes about 11 minutes and 2-3 GB of RAM.

## 0. From a link? Try captions first

If the recording is online, call `fetch_media(url, kind="subtitles")` before anything else. If the
site has captions you get a timestamped `.txt` transcript in seconds, with no Whisper run and no
questions needed (captions don't label speakers, so say so). If there are none, download the audio
with `fetch_media(url, kind="audio")` and continue below.

## 1. Ask first, in one message

Before running anything, ask the user for whatever they haven't already said. Keep it to one short
message and accept "don't know" for any item:

1. **How many people speak?** Passing the exact number is the biggest help with telling voices apart.
2. **Their names**, with roles if helpful ("Tatiana, host; Tanya Richardson, guest; Jordan, Daniel
   and Justine give updates").
3. **Topic, and any names, acronyms or jargon** likely to come up ("US privacy and AI legislation;
   CCPA, Colorado AI Act, EDAA").
4. **Language**, if it isn't English.
5. **Speaker labels needed?** Skipping them saves about 3-4 minutes an hour (e.g. a solo lecture or voice memo).
6. **Where to save it.** Default: next to the audio, same name, `.txt`.

Use AskUserQuestion when it's available. Otherwise use a plain short list.

## 2. Run it

Give the usual one-line heads-up: what's running, a time estimate, and a reminder to close Teams,
Outlook and extra Chrome tabs. Then go ahead without waiting.

- MCP: `transcribe(path, output_path=..., num_speakers=N, speaker_names="A (host), B", context="topic, TERM, Name", language="")`
- Shell (run it in the background, since it takes minutes):
  `transcribe --out OUT.txt --num-speakers N --names "A, B" --context "topic, TERM" AUDIO`

Always save to a file. Don't return the transcript into the conversation.

## 3. Name the speakers from the summary, not the transcript

The result includes a short summary for each speaker: their word count, when they were first heard,
and their opening lines. Match the summary to the names the user gave. Clues: who greets the audience
or hands over the mic ("Thanks, Daniel"), self-introductions, the roles the user described, and who
talks most (usually the host or main speaker). Then call `rename_speakers(path, {"Speaker 4": "Tatiana", ...})`,
or in a shell `transcribe --rename OUT.txt "Speaker 4=Tatiana" ...`.

- Leave a speaker numbered if you can't tell. Say so rather than guessing.
- If one person was split into two labels, map both to the same name.
- Only read parts of the transcript if the summary leaves a real question.

## 4. Report back

Tell the user where the file is, who is who and how confident you are in that, and anything odd
(e.g. a minor speaker who couldn't be identified). Offer a summary next. For a long transcript, use
the local-llm skill to summarize it so the full text stays out of context.
