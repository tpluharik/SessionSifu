import {
    beginShutdown,
    cancelShutdown,
    mayRestoreApplications,
} from '../extension/sessionsifu@local/runtimeSafety.js';


if (!mayRestoreApplications())
    throw new Error('Application restoration should start enabled');
beginShutdown();
if (mayRestoreApplications())
    throw new Error('Application restoration remained enabled during shutdown');
cancelShutdown();
if (!mayRestoreApplications())
    throw new Error('Application restoration did not recover after shutdown cancellation');
