# Skill: ping-test

Pings a host 3 times and reports latency (min/avg/max/stddev).

## Usage

```bash
python3 ~/.nanobot/workspace/skills/ping-test/ping_test.py [host]
```

- Default host: `google.com`
- You can pass any hostname or IP as an argument.

## Examples

```bash
# Ping google.com (default)
python3 ~/.nanobot/workspace/skills/ping-test/ping_test.py

# Ping a custom host
python3 ~/.nanobot/workspace/skills/ping-test/ping_test.py cloudflare.com
```

## Output

Prints raw ping output plus a formatted summary:

```
📡 Ping Summary for google.com:
  Min:    8.23 ms
  Avg:    9.41 ms
  Max:    10.87 ms
  Stddev: 1.12 ms
```

## Requirements

- macOS or Linux (uses system `ping` command)
- No external Python packages needed
