//! The Ctrl+X chord beyond tabs: m model, c config, s stash, p pop, t conversation mode.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use tokio::sync::mpsc;

use crate::app::App;
use crate::focus::Focus;
use crate::server::Client;
use crate::{config, conversation, model_picker, prompt_stash};

/// Armed by Ctrl+X while tabs are off; with tabs on, the tab chord holds the arm.
#[derive(Default)]
pub struct CtrlX {
    armed: bool,
}

enum Action {
    Model,
    Config,
    Stash,
    Pop,
    Conversation,
}

fn action(key: &KeyEvent) -> Option<Action> {
    if !key.modifiers.is_empty() {
        return None;
    }
    match key.code {
        KeyCode::Char('m') => Some(Action::Model),
        KeyCode::Char('c') => Some(Action::Config),
        KeyCode::Char('s') => Some(Action::Stash),
        KeyCode::Char('p') => Some(Action::Pop),
        KeyCode::Char('t') => Some(Action::Conversation),
        _ => None,
    }
}

/// Ctrl+X on the free composer with tabs off arms the chord; the rail still opens with its letters.
pub fn arm(app: &mut App, key: &KeyEvent) {
    let ctrl_x = key.modifiers == KeyModifiers::CONTROL && key.code == KeyCode::Char('x');
    if ctrl_x && !app.session_tabs.enabled && crate::input::composer_reachable(app) {
        app.ctrl_x.armed = true;
    }
}

/// Drop an armed chord, as a priority key does.
pub fn disarm(app: &mut App) {
    app.ctrl_x.armed = false;
}

/// An armed chord takes its key; true when the key ran an action. Any other key disarms it and goes on.
pub fn chord_key(
    app: &mut App,
    client: &Arc<Client>,
    config_tx: &mpsc::Sender<config::Loaded>,
    key: &KeyEvent,
) -> bool {
    let tabs = app.session_tabs.enabled && app.session_tabs.chord && app.focus() == Focus::Composer;
    let own = std::mem::take(&mut app.ctrl_x.armed);
    let Some(action) = action(key).filter(|_| tabs || own) else {
        return false;
    };
    app.session_tabs.chord = false;
    if app.rail.focused {
        crate::rail::leave(app);
    }
    match action {
        Action::Model => model_picker::open_with_catalog_check(app, client),
        Action::Config => config::open(app, client, config_tx),
        Action::Stash => prompt_stash::stash_draft(app),
        Action::Pop => prompt_stash::pop(app),
        Action::Conversation => conversation::toggle(app, client),
    }
    true
}
