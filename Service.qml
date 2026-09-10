import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    property var shell: null
    property var settings: ({})
    property var snapshot: ({projects: [], errors: []})
    property string lastError: ""
    property string message: ""
    property string preview: ""
    property bool previewReady: false
    readonly property bool refreshing: scanProcess.running
    readonly property bool busy: actionProcess.running
    readonly property string helper: String(Qt.resolvedUrl("pr_hunter.py")).replace(/^file:\/\//, "")
    readonly property var projects: snapshot.projects || []
    readonly property int waitingProjects: projects.filter(function(p) { return p.pr_count + p.issue_count > 0 }).length

    function refresh(force) {
        if (scanProcess.running || actionProcess.running) return
        scanProcess.command = ["python3", helper, "scan"].concat(force ? ["--force"] : [])
        scanProcess.running = true
    }
    function act(command, key, scope, pane, path) {
        if (actionProcess.running) return
        previewReady = false
        message = command === "preview" ? "Loading the complete work brief…" : command === "dispatch" ? "Preparing the handoff…" : "Working…"
        var args = ["python3", helper, command, "--key", key, "--scope", scope || "all"]
        if (pane) args = args.concat(["--pane", pane])
        if (path) args = args.concat(["--path", path])
        actionProcess.command = args
        actionProcess.running = true
    }
    Timer { interval: 15000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh(false) }
    Process {
        id: scanProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text)
                    if (result.error) root.lastError = result.error
                    else { root.snapshot = result; root.lastError = (result.errors || []).join("\n") }
                } catch(e) { root.lastError = "Could not read the project scan." }
            }
        }
        stderr: StdioCollector { onStreamFinished: if (text.trim()) root.lastError = text.trim().slice(0, 400) }
        onExited: function(code) { if (code !== 0 && !root.lastError) root.lastError = "Project scan failed. Check Herdr and gh authentication." }
    }
    Process {
        id: actionProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text)
                    root.message = result.error || result.message || "Done"
                    if (result.brief) { root.preview = result.brief; root.previewReady = true }
                } catch(e) { root.message = "The action could not complete." }
            }
        }
        stderr: StdioCollector { onStreamFinished: if (text.trim()) root.message = text.trim().slice(0, 400) }
        onExited: function(code) { Qt.callLater(function() { root.refresh(false) }) }
    }
}
