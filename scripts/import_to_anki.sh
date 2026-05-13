#!/bin/bash
# Opens each Spelling Bee CSV file in Anki's import dialog, then waits
# for you to click the Import button before moving to the next file.
#
# Requirements: Anki must be open; Terminal must have Accessibility permission
# in System Settings > Privacy & Security > Accessibility.
#
# Run: ./scripts/import_to_anki.sh

osascript << 'APPLESCRIPT'

set outputFolder to "/Users/alvazi2/Documents/Projects/SpellingBee/output/"
set csvFiles to {"spelling_bee_complete.csv", "spelling_bee_2_letters.csv", "spelling_bee_3_letters.csv", "spelling_bee_4_letters.csv", "spelling_bee_5_letters.csv", "spelling_bee_6_letters.csv", "spelling_bee_7_letters.csv", "spelling_bee_most_missed.csv"}

tell application "Anki" to activate
delay 1

repeat with csvFile in csvFiles
    set filePath to outputFolder & (csvFile as string)

    tell application "System Events"
        if exists file filePath then
            tell process "Anki"
                set windowsBefore to count of windows

                -- File > Import (Cmd+Shift+I)
                keystroke "i" using {command down, shift down}
                delay 1.5

                -- Navigate to file via Go to Folder sheet
                keystroke "g" using {command down, shift down}
                delay 0.5
                keystroke filePath
                delay 0.3
                key code 36 -- Return: resolve path
                delay 1
                key code 36 -- Return: open file
                delay 2

                -- Alert user that the import dialog is ready
                beep

                -- Wait for user to click Import (dialog window will close)
                -- Timeout after 5 minutes (600 x 0.5s)
                repeat 600 times
                    delay 0.5
                    if (count of windows) <= windowsBefore then exit repeat
                end repeat

                delay 1
            end tell
        end if
    end tell
end repeat

beep 3

APPLESCRIPT
