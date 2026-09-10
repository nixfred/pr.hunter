import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root
    moduleName: "nixfred.pr-hunter"
    manageIpc: false
    implicitWidth: barButton.implicitWidth
    implicitHeight: barButton.implicitHeight
    readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
    readonly property var projects: service ? service.projects : []
    property string selectedKey: ""
    property string selectedPane: ""
    property string scope: "all"
    property bool showBrief: false
    property string search: ""
    readonly property var current: projects.find(function(p) { return p.key === root.selectedKey }) || null
    readonly property var filtered: projects.filter(function(p) {
        return (p.label + " " + p.repos.map(function(r) { return r.name }).join(" ")).toLowerCase().indexOf(root.search.toLowerCase()) >= 0
    })
    readonly property color ink: Color.popups.text
    readonly property color muted: Qt.alpha(ink, 0.65)
    readonly property color highlight: Qt.tint(ink, Qt.alpha(Color.accent, 0.35))

    function syncRows() {
        if (!list) return
        var previous = list.contentY
        list.model = filtered
        Qt.callLater(function() { list.contentY = Math.max(0, Math.min(previous, list.contentHeight - list.height)) })
    }
    onFilteredChanged: syncRows()
    Component.onCompleted: syncRows()

    function detail(project) {
        selectedKey = project.key
        selectedPane = project.agents.length === 1 ? project.agents[0].pane_id : ""
        showBrief = false
        mappingPath.text = project.paths.length ? project.paths[0] : ""
    }
    function dispatch(project) {
        if (!service || service.busy) return
        if (!project.repos.length || project.agents.length !== 1) { detail(project); return }
        root.close()
        service.act("dispatch", project.key, scope, project.agents[0].pane_id, "")
    }
    function counts(project) {
        var repos = project.repos.filter(function(r) { return scope === "all" || (scope === "mine" ? r.own : !r.own) })
        var prs = 0, issues = 0
        for (var i = 0; i < repos.length; i++) {
            prs += repos[i].pullRequests ? repos[i].pullRequests.totalCount : 0
            issues += repos[i].issues ? repos[i].issues.totalCount : 0
        }
        return prs + " PR" + (prs === 1 ? "" : "s") + "  ·  " + issues + " issue" + (issues === 1 ? "" : "s")
    }
    onOpenedChanged: if (opened && service) service.refresh(false)
    IpcHandler {
        target: "nixfred.pr-hunter"
        function open(): void { root.open() }
        function close(): void { root.close() }
        function toggle(): void { root.toggle() }
        function select(key: string): void {
            var p = root.projects.find(function(p) { return p.key === key })
            if (p) { root.detail(p); root.open() }
        }
        function status(): string {
            return JSON.stringify({opened: root.opened, version: "1.0.0", projects: root.projects.length,
                waiting: root.service ? root.service.waitingProjects : 0, busy: root.service ? root.service.busy : false,
                error: root.service ? root.service.lastError : "Service not loaded", message: root.service ? root.service.message : "",
                selected: root.selectedKey, scrollY: list.contentY, maxScroll: Math.max(0, list.contentHeight-list.height), previewReady: root.service ? root.service.previewReady : false,
                rows: root.filtered.map(function(p) { return {key:p.key,label:p.label,prs:p.pr_count,issues:p.issue_count,agent:p.agent_status} })})
        }
        function refresh(): void { if (root.service) root.service.refresh(true) }
        function preview(key: string): void {
            var p = root.projects.find(function(p) { return p.key === key })
            if (p) { root.detail(p); root.showBrief = true; root.open(); root.service.act("preview", key, root.scope, root.selectedPane, "") }
        }
        function scrollTo(position: real): void { root.selectedKey = ""; list.contentY = Math.max(0, Math.min(position, list.contentHeight - list.height)) }
    }
    WidgetButton {
        id: barButton
        bar: root.bar
        anchors.fill: parent
        text: "󰊢 " + (root.service ? String(root.service.waitingProjects) : "…")
        tooltipText: "PR Hunter · " + root.projects.length + " Herdr projects\nClick to open PRs, issues and session handoffs"
        onPressed: root.toggle()
    }
    PopupCard {
        id: popup
        bar: root.bar
        anchorItem: root
        owner: root
        open: root.opened
        contentWidth: fittedContentWidth(680)
        contentHeight: cappedContentHeight(760)

        Item {
            anchors.fill: parent
            Column {
                id: header
                width: parent.width
                spacing: 8
                Row {
                    width: parent.width
                    Text { text: "PR HUNTER"; color: root.ink; font.family: Style.font.family; font.pixelSize: 21; font.bold: true; font.letterSpacing: 1; width: parent.width - refreshButton.width }
                    Button { id: refreshButton; text: root.service && root.service.refreshing ? "Checking…" : "Refresh"; enabled: root.service && !root.service.refreshing && !root.service.busy; onClicked: root.service.refresh(true) }
                }
                Text { width: parent.width; text: root.current ? root.current.label + "  /  " + root.current.session : root.projects.length + " open projects · click a project to open its session and send work"; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 12; textFormat: Text.PlainText }
                Row {
                    spacing: 5
                    Button { text: "All remotes"; selected: root.scope === "all"; onClicked: root.scope = "all" }
                    Button { text: "Your repos"; selected: root.scope === "mine"; onClicked: root.scope = "mine" }
                    Button { text: "Upstream"; selected: root.scope === "upstream"; onClicked: root.scope = "upstream" }
                    Button { visible: root.current !== null; text: "← Projects"; onClicked: { root.selectedKey = ""; root.showBrief = false } }
                }
                TextField { width: parent.width; visible: !root.current; placeholderText: "Find a project or repository…"; onTextChanged: root.search = text }
                Text {
                    width: parent.width
                    visible: text.length > 0
                    text: root.service ? root.service.lastError || root.service.message : "Starting PR Hunter…"
                    color: root.service && root.service.lastError ? Color.urgent : root.highlight
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }
            }
            ListView {
                id: list
                visible: !root.current
                anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: footer.top; topMargin: 12; bottomMargin: 10 }
                model: []
                spacing: 6
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    width: list.width - 12
                    height: 88
                    radius: Math.max(4, Style.cornerRadius)
                    color: Qt.alpha(root.ink, rowMouse.containsMouse ? 0.10 : 0.035)
                    border.color: Qt.alpha(root.ink, 0.12)
                    MouseArea {
                        id: rowMouse
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; right: details.left; rightMargin: 6 }
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        enabled: !root.service || !root.service.busy
                        onClicked: root.dispatch(row.modelData)
                    }
                    Column {
                        anchors { left: parent.left; leftMargin: 12; right: details.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        spacing: 5
                        Text { width: parent.width; text: row.modelData.label; color: root.ink; font.pixelSize: 16; font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                        Text { width: parent.width; text: row.modelData.error ? "GitHub unavailable · Details" : row.modelData.repos.length ? root.counts(row.modelData) + (row.modelData.upstream_count && root.scope === "all" ? " · includes upstream" : "") : "Repository needs mapping"; color: row.modelData.error ? Color.urgent : root.highlight; font.pixelSize: 13; elide: Text.ElideRight; textFormat: Text.PlainText }
                        Text { width: parent.width; text: row.modelData.job.status === "queued" ? "Queued · waiting for agent" : row.modelData.job.message || row.modelData.agent_status + " · " + row.modelData.session; color: root.muted; font.pixelSize: 12; elide: Text.ElideRight; textFormat: Text.PlainText }
                    }
                    Button { id: details; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: "Details"; onClicked: root.detail(row.modelData) }
                }
                Text { visible: list.count === 0; anchors.centerIn: parent; text: root.projects.length ? "No matching projects" : "Waiting for an open Herdr session…"; color: root.muted; font.pixelSize: 14 }
            }
            Flickable {
                id: detailScroll
                visible: root.current !== null
                anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: footer.top; topMargin: 12; bottomMargin: 10 }
                contentWidth: width
                contentHeight: detailColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
                Column {
                    id: detailColumn
                    width: detailScroll.width - 14
                    spacing: 12
                    Text { width: parent.width; text: root.current ? root.counts(root.current) : ""; color: root.highlight; font.pixelSize: 19; font.bold: true }
                    Repeater {
                        model: root.current ? root.current.repos : []
                        delegate: Column {
                            required property var modelData
                            width: detailColumn.width
                            spacing: 4
                            Text { width: parent.width; text: modelData.name + (modelData.own ? "  ·  yours" : "  ·  upstream"); color: root.ink; font.pixelSize: 13; elide: Text.ElideRight; textFormat: Text.PlainText }
                            Text { width: parent.width; text: modelData.error || ((modelData.pullRequests ? modelData.pullRequests.totalCount : "?") + " PRs · " + (modelData.hasIssuesEnabled === false ? "issues disabled" : (modelData.issues ? modelData.issues.totalCount : "?") + " issues") + (modelData.checked ? " · checked " + new Date(modelData.checked * 1000).toLocaleTimeString() : "")); color: modelData.error ? Color.urgent : root.muted; font.pixelSize: 11; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        }
                    }
                    Text { width: parent.width; text: "Send to the existing agent"; color: root.ink; font.pixelSize: 13; font.bold: true }
                    Repeater {
                        model: root.current ? root.current.agents : []
                        delegate: Button {
                            required property var modelData
                            text: modelData.agent + " · " + modelData.pane_id + " · " + modelData.agent_status
                            selected: root.selectedPane === modelData.pane_id
                            onClicked: root.selectedPane = modelData.pane_id
                        }
                    }
                    Text { width: parent.width; visible: root.current !== null && !root.current.agents.length; text: "No supported local agent detected. Open the session to inspect it. Remote SSH terminals need a local Herdr agent connection before a handoff can be sent."; color: root.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                    Flow {
                        width: parent.width
                        spacing: 6
                        Button { text: "Open & process"; enabled: root.current !== null && root.selectedPane.length > 0 && root.current.repos.length > 0 && root.service && !root.service.busy; onClicked: { root.close(); root.service.act("dispatch", root.current.key, root.scope, root.selectedPane, "") } }
                        Button { text: "Preview brief"; enabled: root.current !== null && root.selectedPane.length > 0 && root.current.repos.length > 0 && root.service && !root.service.busy; onClicked: { root.showBrief = true; root.service.act("preview", root.current.key, root.scope, root.selectedPane, "") } }
                        Button { text: "Open session"; enabled: root.current !== null && root.service && !root.service.busy; onClicked: { root.close(); root.service.act("focus", root.current.key, root.scope, root.selectedPane, "") } }
                        Button { text: "Cancel queue"; visible: root.current !== null && root.current.job.status === "queued"; onClicked: root.service.act("cancel", root.current.key, root.scope, "", "") }
                    }
                    Text { width: parent.width; text: root.current ? root.current.job.message || "A click sends new or updated items. Busy agents wait until ready." : ""; color: root.muted; wrapMode: Text.Wrap; font.pixelSize: 12; textFormat: Text.PlainText }
                    Text { width: parent.width; text: "Repository checkout"; color: root.ink; font.pixelSize: 13; font.bold: true }
                    TextField { id: mappingPath; width: parent.width; placeholderText: "/path/to/project" }
                    Button { text: "Save mapping"; enabled: root.current !== null && mappingPath.text.length > 0 && root.service && !root.service.busy; onClicked: root.service.act("map", root.current.key, "all", "", mappingPath.text) }
                    Text {
                        width: parent.width
                        visible: root.showBrief && root.service && root.service.previewReady
                        text: root.service ? root.service.preview : ""
                        textFormat: Text.PlainText
                        color: root.ink
                        font.family: Style.font.family
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }
            Text {
                id: footer
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                text: "PR Hunter 1.0.0 · GitHub every 5 min · projects every 15 sec\nReview, fix, test and push. Merges and issue closure need your decision."
                color: root.muted
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }
        }
    }
}
