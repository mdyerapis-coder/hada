#!/usr/bin/env python3
"""Headless gcloud auth helper for Hermes.

Runs `gcloud auth login --no-launch-browser` inside a pty, captures the
OAuth URL live, and writes it to --url-file. Then waits until --code-file
exists (you paste the verification code there), feeds it to the live gcloud
process, and reports success/failure.

This NEVER deploys anything. It only authenticates your personal principal
to gcloud so IAP/OS-Login scoped SSH to hada-control becomes possible.
"""
import sys, time, argparse, re, os
import pexpect

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url-file", default="/tmp/gcloud_oauth_url.txt")
    ap.add_argument("--code-file", default="/tmp/gcloud_code.txt")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    child = pexpect.spawn("gcloud", ["auth", "login", "--no-launch-browser"],
                          timeout=30, encoding="utf-8")
    child.logfile = open("/tmp/gcloud_auth_pexpect.log", "w")

    url = None
    # 1) answer GCE warning (Y) if asked, then capture URL
    seen_prompt = False
    try:
        while True:
            i = child.expect([
                r"Do you want to continue \(Y/n\)\?\s*",
                r"Go to the following link in your browser.*?\n\s*(https://accounts\.google\.com/[^\n]+)",
                r"(?i)enter the verification code provided in your browser:\s*",
                r"ERROR:",
                r"You are now logged in",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ])
            if i == 0:
                child.sendline("Y")
            elif i == 1:
                # group 1 holds the URL (may span the matched line)
                url = child.match.group(1).strip()
                with open(args.url_file, "w") as f:
                    f.write(url + "\n")
                print("URL_READY:" + url, flush=True)
            elif i == 2:
                seen_prompt = True
                break
            elif i == 3:
                print("GCL_ERROR:" + child.before, flush=True)
                child.close()
                return 1
            elif i == 4:
                print("ALREADY_LOGGED_IN", flush=True)
                child.close()
                return 0
            elif i == 5:
                print("GCL_EOF", flush=True)
                return 1
            elif i == 6:
                # timeout waiting for something; if we have the URL but no code
                # prompt yet, keep looping; else bail.
                if url and not seen_prompt:
                    continue
                print("GCL_TIMEOUT", flush=True)
                return 1
    except pexpect.exceptions as e:
        print("PEXPECT_ERR:" + str(e), flush=True)
        return 1

    if not url:
        print("NO_URL_CAPTURED", flush=True)
        return 1

    # 2) wait for you to paste the code
    print("WAITING_FOR_CODE", flush=True)
    waited = 0
    while not os.path.exists(args.code_file) or os.path.getsize(args.code_file) == 0:
        time.sleep(2)
        waited += 2
        if waited > args.timeout:
            print("CODE_TIMEOUT", flush=True)
            child.close()
            return 1

    with open(args.code_file) as f:
        code = f.read().strip()
    if not code:
        print("EMPTY_CODE", flush=True)
        child.close()
        return 1

    child.logfile.flush()
    child.sendline(code)
    print("CODE_SENT:" + code[:6] + "...", flush=True)
    child.logfile.flush()

    # 3) confirm success
    try:
        j = child.expect([
            r"You are now logged in as ([\w\.\-@]+)",
            r"ERROR:",
            r"invalid",
            pexpect.EOF,
            pexpect.TIMEOUT,
        ], timeout=60)
        if j == 0:
            acct = child.match.group(1)
            print("AUTH_SUCCESS:" + acct, flush=True)
            child.close()
            return 0
        elif j in (1, 2):
            print("AUTH_FAILED:" + child.before, flush=True)
            child.close()
            return 1
        else:
            print("AUTH_UNKNOWN_STATE", flush=True)
            child.close()
            return 1
    except pexpect.exceptions as e:
        print("CONFIRM_ERR:" + str(e), flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
