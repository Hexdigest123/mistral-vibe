//! Tab keys on the composer: Tab/Shift+Tab step through the tabs, Alt+1-9 jump.

use std::sync::Arc;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::app::App;
use crate::focus::Focus;
use crate::server::Client;

use super::{step, switch_to, switchable};

/// Handle `key` when the composer owns it; true when it switched tabs.
pub fn handle_key(app: &mut App, client: &Arc<Client>, key: &KeyEvent) -> bool {
    if !switchable(app) || app.focus() != Focus::Composer {
        return false;
    }
    // Queue selection, history search and the completion popup own their keys.
    if app.queue.selected.is_some()
        || app.reverse_search.is_some()
        || app.chat_input.mode != crate::input_modes::InputMode::Prompt
    {
        return false;
    }
    match key.code {
        KeyCode::Tab if key.modifiers.is_empty() && !crate::completion_manager::is_open(app) => {
            step(app, client, 1);
            true
        }
        KeyCode::BackTab if key.modifiers.contains(KeyModifiers::SHIFT) => {
            step(app, client, -1);
            true
        }
        KeyCode::Char(digit @ '1'..='9') if key.modifiers == KeyModifiers::ALT => {
            let index = digit as usize - '0' as usize - 1;
            if index < app.session_tabs.list.len() {
                switch_to(app, client, index);
                return true;
            }
            false
        }
        _ => false,
    }
}
