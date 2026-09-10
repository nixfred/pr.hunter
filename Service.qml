import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    readonly property string version: "1.1.0"
    property var shell: null
    property var settings: ({})
    property var snapshot: ({projects: [], errors: []})
    property string lastError: ""
    property string message: ""
    property string preview: ""
    property bool previewReady: false
    property string activeCommand: ""
    property var pendingAction: null
    property bool refreshPending: false
    property bool forcePending: false
    property bool stdoutDone: false
    property bool stderrDone: false
    property bool exited: false
    property bool timedOut: false
    property int helperTimeout: 300000
    property int exitCode: 0
    property string stdoutText: ""
    property string stderrText: ""
    readonly property bool refreshing: activeCommand === "scan"
    readonly property bool busy: pendingAction !== null || (activeCommand !== "" && activeCommand !== "scan")
    property string helper: decodeURIComponent(String(Qt.resolvedUrl("pr_hunter.py")).replace(/^file:\/\/(localhost)?/, ""))
    readonly property var projects: snapshot.projects || []
    readonly property int waitingProjects: projects.filter(function(p) { return p.pr_count + p.issue_count > 0 }).length

    function start(command, args) {
        activeCommand = command
        stdoutDone = false; stderrDone = false; exited = false; timedOut = false
        stdoutText = ""; stderrText = ""; exitCode = 0
        worker.command = ["python3", helper, command].concat(args)
        worker.running = true
        watchdog.restart()
    }
    function refresh(force) {
        if (activeCommand !== "") {
            if (force) { refreshPending = true; forcePending = true }
            return
        }
        start("scan", force ? ["--force"] : [])
    }
    function act(command, key, scope, pane, path) {
        if (busy) return
        previewReady = false
        message = command === "preview" ? "Loading the complete work brief…" : command === "dispatch" ? "Preparing the handoff…" : "Working…"
        var args = ["--key=" + key, "--scope=" + (scope || "all")]
        if (pane) args.push("--pane=" + pane)
        if (path) args.push("--path=" + path)
        if (activeCommand !== "") pendingAction = {command: command, args: args}
        else start(command, args)
    }
    function normalize(result) {
        if (!Array.isArray(result.projects)) throw new Error("Missing projects")
        result.projects = result.projects.filter(function(p) { return p && typeof p.key === "string" }).map(function(p) {
            p.repos = Array.isArray(p.repos) ? p.repos : []
            p.agents = Array.isArray(p.agents) ? p.agents : []
            p.paths = Array.isArray(p.paths) ? p.paths : []
            p.open = p.open !== false
            p.job = p.job || {}
            p.label = p.label || "Untitled project"
            p.session = p.session || ""
            p.pr_count = Number(p.pr_count) || 0
            p.issue_count = Number(p.issue_count) || 0
            return p
        })
        return result
    }
    function finish() {
        // A process exit can arrive before either pipe has finished draining.
        if (!exited || !stdoutDone || !stderrDone) return
        watchdog.stop()
        var command = activeCommand
        try {
            if (timedOut) throw new Error("Helper timed out. Inspect the session before retrying a handoff.")
            var result = JSON.parse(stdoutText)
            if (result.error) throw new Error(result.error)
            if (exitCode !== 0) throw new Error(stderrText.trim() || "Helper exited with code " + exitCode)
            if (command === "scan") { snapshot = normalize(result); lastError = (result.errors || []).join("\n") }
            else {
                message = result.message || "Done"
                if (result.brief) { preview = result.brief; previewReady = true }
            }
        } catch(e) {
            var problem = String(e.message || e).slice(0, 800)
            if (!stdoutText.trim() && !timedOut && stderrText.trim()) problem = stderrText.trim().slice(0, 800)
            if (command === "scan") lastError = problem
            else message = problem
        }
        activeCommand = ""
        if (pendingAction !== null) {
            var action = pendingAction
            pendingAction = null
            start(action.command, action.args)
        } else if (command !== "scan" || refreshPending) {
            var force = forcePending
            refreshPending = false; forcePending = false
            refresh(force)
        }
    }
    Timer { interval: 15000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh(false) }
    Timer {
        id: watchdog
        interval: root.helperTimeout
        onTriggered: {
            root.timedOut = true
            if (worker.running) worker.signal(9)
            else {
                root.stdoutDone = true; root.stderrDone = true; root.exited = true
                root.finish()
            }
        }
    }
    Process {
        id: worker
        stdout: StdioCollector { onStreamFinished: { root.stdoutText = text; root.stdoutDone = true; root.finish() } }
        stderr: StdioCollector { onStreamFinished: { root.stderrText = text; root.stderrDone = true; root.finish() } }
        onExited: function(code) { root.exitCode = code; root.exited = true; root.finish() }
    }
}
