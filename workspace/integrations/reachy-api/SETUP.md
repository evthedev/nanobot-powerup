# Installing NanoBot on Reachy Mini

I'm sending you a file called `install.sh` via WhatsApp. Follow these steps to install it on Reachy.

> **If anything goes wrong, screenshot the error and send it to me.**

---

## Step 1 — Save the file

Save `install.sh` from WhatsApp to your **Desktop**.

---

## Step 2 — Find Reachy's IP address

The IP address looks like four numbers separated by dots, e.g. `192.168.1.42`.

Check Reachy's touchscreen or web interface for it. If you can't find it:

1. Press the **Windows key**, type `cmd`, press **Enter**
2. Paste this and press **Enter**:
   ```
   ping reachy.local
   ```
3. The IP address will appear in brackets — e.g. `Pinging reachy.local [192.168.1.42]`

Write it down. You'll need it in the next steps.

---

## Step 3 — Open Command Prompt

Press the **Windows key**, type `cmd`, press **Enter**.

---

## Step 4 — Copy the file to Reachy

Paste this into Command Prompt. **Replace `192.168.1.42` with Reachy's actual IP from Step 2.**

```
scp %USERPROFILE%\Desktop\install.sh reachy@192.168.1.42:~/install_nanobot.sh
```

Press **Enter**. It will ask for a password — type Reachy's password and press **Enter**.

> Nothing appears as you type the password. That's normal.

---

## Step 5 — Connect to Reachy

Paste this. **Replace `192.168.1.42` with Reachy's IP.**

```
ssh reachy@192.168.1.42
```

Press **Enter** and type the password again.

You'll know it worked when you see something like:
```
reachy@reachy-mini:~$
```

---

## Step 6 — Run the installer

Paste this and press **Enter**:

```
bash ~/install_nanobot.sh
```

Wait about 30–60 seconds. You'll see green ticks (✔) appearing as it runs.

**Wait until you see:**
```
Installation complete.
```

If you see a red ✖ at any point, screenshot it and send it to me.

---

## Step 7 — Restart Reachy's conversation app

If Reachy was already running, restart it. Run these three commands **one at a time**:

```
cd ~/reachy_mini_conversation_app
```

```
source .venv/bin/activate
```

```
reachy-mini-conversation-app
```

---

## Step 8 — Confirm it worked

Watch the text that appears after the last command. Look for this line:

```
✓ Loaded external tool: call_nanobot
```

Once you see it, **send me a screenshot**. You're done! 🎉
