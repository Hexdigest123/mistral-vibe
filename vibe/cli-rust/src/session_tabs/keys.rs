//! The Ctrl+X chord on the composer: Ctrl+X, then 1-9 switches to that tab,
//! n opens a new one, c closes the active one; any other key cancels the chord.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::app::App;
use crate::focus::Focus;
use crate::server::Client;

use super::{close, new_tab, switch_to};

/// Handle `key` when the composer owns it; true when it was a chord key.
pub fn handle_key(app: &mut App, client: &Arc<Client>, key: &KeyEvent) -> bool {
    if !app.session_tabs.enabled || app.focus() != Focus::Composer {
        return false;
    }
    if app.session_tabs.chord {
        return chord_key(app, client, key);
    }
    // Queue selection, history search and the completion popup own their keys.
    if app.queue.selected.is_some()
        || app.reverse_search.is_some()
        || app.chat_input.mode != crate::input_modes::InputMode::Prompt
        || crate::completion_manager::is_open(app)
    {
        return false;
    }
    // The chord owns Ctrl+X from the composer whenever the feature is on, even
    // with a single tab: Ctrl+X n is how a second tab gets opened.
    if key.modifiers == KeyModifiers::CONTROL && key.code == KeyCode::Char('x') {
        app.session_tabs.chord = true;
        true
    } else {
        false
    }
}

/// An armed chord takes the next key before any composer-level binding (Left
/// opening the Sessions page included): 1-9/n/c drive the tabs; any other key
/// cancels the chord and reaches the rail, as Ctrl+X would have without it.
pub fn chord_key(app: &mut App, client: &Arc<Client>, key: &KeyEvent) -> bool {
    if !app.session_tabs.enabled || app.focus() != Focus::Composer || !app.session_tabs.chord {
        return false;
    }
    app.session_tabs.chord = false;
    if key.modifiers.is_empty() {
        match key.code {
            KeyCode::Char(digit @ '1'..='9') => {
                let index = digit as usize - '0' as usize - 1;
                if index < app.session_tabs.list.len() {
                    switch_to(app, client, index);
                }
                return true;
            }
            KeyCode::Char('n') => {
                new_tab(app, client);
                return true;
            }
            KeyCode::Char('c') => {
                let active = app.session_tabs.active;
                close(app, client, active);
                return true;
            }
            _ => {}
        }
    }
    if crate::input::composer_reachable(app) && crate::rail::enter(app) {
        crate::rail::handle_key(app, client, key);
    }
    true
}
