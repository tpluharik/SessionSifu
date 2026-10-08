import {
    beginShutdown,
    cancelShutdown,
    mayRestoreApplications,
    layoutSafety,
    configureLayoutSafety,
    beginMonitorChange,
    mayRestoreLayout,
} from '../extension/sessionsifu@local/runtimeSafety.js';


if (!mayRestoreApplications())
    throw new Error('Application restoration should start enabled');
beginShutdown();
if (mayRestoreApplications())
    throw new Error('Application restoration remained enabled during shutdown');
cancelShutdown();
if (!mayRestoreApplications())
    throw new Error('Application restoration did not recover after shutdown cancellation');

let now = 0;
configureLayoutSafety(() => now);
const initialGeneration = layoutSafety.generation;
beginMonitorChange();
if (mayRestoreLayout() || !mayRestoreApplications())
    throw new Error('Monitor quiet period must pause layout, not application launch');
now = 900;
beginMonitorChange();
now = 1000;
if (mayRestoreLayout())
    throw new Error('Repeated hotplug must extend the quiet period');
now = 1900;
if (!mayRestoreLayout() || mayRestoreLayout(initialGeneration))
    throw new Error('Only fresh layout work may resume after monitor settlement');
const beforeShutdown = layoutSafety.generation;
beginShutdown();
cancelShutdown();
if (mayRestoreLayout(beforeShutdown))
    throw new Error('Shutdown cancellation must not resurrect old native work');
