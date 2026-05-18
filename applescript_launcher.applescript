-- Claude Local launcher.
-- AppleScript wrapper around the shell launcher so macOS re-runs us on
-- subsequent double-clicks. The 'reopen' handler fires whenever the user
-- activates the .app while it's "running" — which for a detached server
-- happens immediately because we exit after spawning.

property serverPort : 8765

on run
	launchOrReopen()
end run

on reopen
	launchOrReopen()
end reopen

on launchOrReopen()
	if isServerUp() then
		openInBrowser()
	else
		startServer()
		-- Wait briefly for the server to come up, then open the browser.
		set retries to 0
		repeat while retries < 25
			if isServerUp() then
				openInBrowser()
				return
			end if
			delay 0.4
			set retries to retries + 1
		end repeat
		-- Server didn't come up — show a diagnostic dialog with the log tail.
		set logPath to (POSIX path of (path to home folder)) & "Library/Logs/ClaudeLocal.log"
		try
			set tailText to do shell script "tail -8 " & quoted form of logPath
		on error
			set tailText to "(no log yet)"
		end try
		display dialog "Claude Local server failed to start within 10 seconds." & return & return & "Last log lines:" & return & tailText buttons {"OK"} default button "OK" with icon stop with title "Claude Local"
	end if
end launchOrReopen

on isServerUp()
	try
		do shell script "/usr/bin/curl -fsS --max-time 1 http://localhost:" & serverPort & "/api/config > /dev/null"
		return true
	on error
		return false
	end try
end isServerUp

on openInBrowser()
	do shell script "/usr/bin/open " & quoted form of ("http://localhost:" & serverPort & "/")
end openInBrowser

on startServer()
	set bundlePath to POSIX path of (path to me)
	set launcher to bundlePath & "Contents/Resources/launcher.sh"
	-- Detach so this AppleScript can exit and macOS treats the .app as
	-- "not running" — re-launches will then reach this 'on reopen' handler.
	do shell script "nohup " & quoted form of launcher & " > /dev/null 2>&1 &"
end startServer
