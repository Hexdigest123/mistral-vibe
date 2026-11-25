//! A tab switch makes the callbacks of the session left moot: their UI closes unanswered.

use crate::app::App;

/// Close the approvals and questions of the session `left`; the server keeps them
/// for it and re-sends them when it is attached again.
pub(super) fn drop_callbacks(app: &mut App, left: &str) {
    app.approval.forget(Some(left));
    crate::question_app::forget(app, Some(left));
    if !crate::question_app::callback_active(app)
        && app.approval.active.is_none()
        && !app.approval.has_pending()
    {
        app.view.loading.end_action_required();
    }
}
