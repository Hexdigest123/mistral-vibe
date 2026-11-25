//! Slash-command resolution: aliases, bare exit synonyms, arguments and side-channel routing.

use vibe_rs::commands::{argument_hint, is_deferred, is_side_channel, parse, waits_for_jobs};
use vibe_rs::input_modes::{classify, ClassifiedInput};

#[test]
fn aliases_resolve_to_their_canonical_command() {
    for (input, canonical) in [
        ("/help", "/help"),
        ("/new", "/clear"),
        ("/clean", "/clear"),
        ("/continue", "/resume"),
        ("/connectors", "/mcp"),
        ("/fork", "/branch"),
        (":q", "/exit"),
        (":quit", "/exit"),
    ] {
        assert_eq!(parse(input), Some(canonical), "{input}");
    }
}

#[test]
fn command_words_are_case_insensitive_and_trimmed() {
    assert_eq!(parse("/HELP"), Some("/help"));
    assert_eq!(parse("  /Model  "), Some("/model"));
    assert_eq!(parse("/Connectors"), Some("/mcp"));
    assert_eq!(parse("/FORK"), Some("/branch"));
}

#[test]
fn unknown_words_are_not_commands() {
    assert_eq!(parse("/definitely-not-a-command"), None);
    assert_eq!(parse("hello"), None);
    assert_eq!(parse(""), None);
}

#[test]
fn slash_commands_keep_their_arguments() {
    assert_eq!(parse("/clear seed the next conversation"), Some("/clear"));
    assert_eq!(parse("/new seed"), Some("/clear"));
    assert_eq!(parse("/exit now"), Some("/exit"));
    assert_eq!(argument_hint(Some('/'), "clear "), Some("[prompt]"));
    assert_eq!(argument_hint(Some('/'), "new "), Some("[prompt]"));
}

#[test]
fn bare_exit_synonyms_exit_only_as_the_whole_input() {
    for input in ["exit", "quit", "EXIT", "Quit", " exit ", ":Q"] {
        assert_eq!(parse(input), Some("/exit"), "{input:?}");
        assert_eq!(
            classify(input, &[]),
            ClassifiedInput::SlashCommand { command: "/exit" },
            "{input:?}"
        );
    }
    for input in [
        "exit the function early",
        "quit your job",
        "exit\nplease refactor this module",
    ] {
        assert_eq!(parse(input), None, "{input:?}");
        assert_eq!(
            classify(input, &[]),
            ClassifiedInput::Prompt {
                text: input.to_owned()
            },
            "{input:?}"
        );
    }
}

#[test]
fn only_history_rewrites_wait_for_idle_and_every_other_command_runs_while_busy() {
    for command in ["/clear", "/compact", "/rewind", "/resume", "/retry"] {
        assert!(is_deferred(command), "{command} is scheduled for idle");
    }
    for command in [
        "/config",
        "/model",
        "/thinking",
        "/reload",
        "/mcp",
        "/connectors",
        "/plugins",
        "/reload-plugins",
        "/skills",
        "/agent",
        "/cd",
        "/tab",
        "/help",
        "/sessions",
        "/theme",
        "/branch",
    ] {
        assert!(!is_deferred(command), "{command} runs at once while busy");
    }
}

#[test]
fn commands_a_turn_never_reads_stay_side_channel_commands() {
    for command in [
        "/help",
        "/status",
        "/whoami",
        "/copy",
        "/raw",
        "/log",
        "/debug",
        "/rename",
        "/data-retention",
        "/exit",
        "/theme",
        "/log-level",
        "/voice",
        "/proxy-setup",
        "/branch",
        "/fork",
        "/skills",
    ] {
        assert!(is_side_channel(command), "{command} runs while busy");
    }
}

#[test]
fn side_channel_settings_wait_for_running_jobs() {
    for command in [
        "/theme",
        "/log-level",
        "/voice",
        "/proxy-setup",
        "/branch",
        "/skills",
    ] {
        assert!(waits_for_jobs(command), "{command} waits for jobs");
    }
    for command in ["/help", "/exit", "/status"] {
        assert!(!waits_for_jobs(command), "{command} runs during jobs");
    }
}
