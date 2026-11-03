# How to install Sage Study

Sage Study makes quizzes, study guides, and video playlists from your own notes and slides.

## Before you start

You need two things from Anthropic, the company behind Claude:

1. **A Claude plan that includes Claude Code.** The free plan doesn't include it. See the [plans](https://claude.com/pricing).
2. **Claude Code on your computer.** Follow [Anthropic's instructions](https://code.claude.com/docs/en/setup). Afterwards, open Terminal (Mac) or PowerShell (Windows), type `claude`, press Enter, and follow the steps to sign in.

Sage Study walks you through this too, so it's fine to install it first. Using it counts toward your own plan's limits.

## On Windows

1. Go to the [Sage Study page](https://github.com/kfcasey7/sage-study), click the green **Code** button, then click **Download ZIP**.
2. Open your Downloads folder, right-click the ZIP file, and choose **Extract All**.
3. Open the new folder and double-click **Install.bat**.
4. If you see "Windows protected your PC", click **More info**, then **Run anyway**. This warning appears because the app isn't registered with Microsoft.
5. Wait a few minutes. Sage Study opens by itself when it's ready, and you'll have an icon on your Desktop.

You can delete the downloaded folder afterwards.

## On a Mac

1. Open **Terminal**: press Cmd and Space together, type `Terminal`, and press Return.
2. Copy this whole line, paste it into Terminal, and press Return:

   ```
   curl -fsSL https://raw.githubusercontent.com/kfcasey7/sage-study/main/install.sh | sh
   ```

3. Wait a few minutes. Sage Study opens by itself when it's ready. You can also find it on your Desktop.

## The first time it opens

You'll see a short checklist. A green check means that part is ready. Anything else comes with instructions, and a **Check again** button for when you've done it. Click **Try a demo** to look around without uploading anything.

## Good to know

- **Your files stay on your computer.** When you use a feature that needs AI, your material is sent to Anthropic through your own account.
- **Updates:** a small banner appears when there's a new version. Nothing changes until you click it.
- **To remove it on Windows:** Start Menu > **Uninstall Sage Study**.
- **To remove it on a Mac:** open Terminal and paste `sh ~/Library/Application\ Support/SageStudy-App/uninstall.sh`, then press Return.
- It will ask before deleting your study data.

## If something goes wrong

Running the installer again is always safe, and it fixes most problems. If you're still stuck, open **Settings > Help > Diagnostics** in the app, click **Copy diagnostic report**, and send it to whoever shared this with you. It doesn't include anything private.

Sage Study is unofficial, and isn't made or endorsed by Anthropic.
