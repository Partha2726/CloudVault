---
name: CloudVault
description: A private document vault on a simulated S3 store, presented as an archive's finding aid.
colors:
  shell: "#2e3a40"
  shell-raised: "#3a474e"
  shell-ink: "#f4f6f5"
  shell-muted: "#b8c4c9"
  ink: "#1d2427"
  ink-muted: "#56636a"
  ink-faint: "#5f6c73"
  ground: "#eef0ee"
  panel: "#ffffff"
  rule: "#d6dbd8"
  rule-strong: "#b9c1bd"
  class-standard: "#2e3a40"
  class-ia: "#5e7480"
  class-gir: "#9fb3bc"
  accent: "#5e7480"
  accent-strong: "#44565f"
  ok: "#3f6e4f"
  alert: "#b23a2f"
typography:
  display:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  figure:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.025em"
    fontFeature: "\"tnum\" 1, \"lnum\" 1"
  headline:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
  lead:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  body:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.43
  note:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  caption:
    fontFamily: "Public Sans Variable, Public Sans, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: "0.08em"
rounded:
  record: "2px"
spacing:
  row-tight: "10px"
  row: "16px"
  inset-sm: "20px"
  inset: "24px"
  gap: "24px"
  section: "32px"
components:
  record-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.record}"
  panel-header:
    typography: "{typography.title}"
    textColor: "{colors.ink}"
    padding: "12px 24px"
  button-primary:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.record}"
    padding: "10px 12px"
  button-primary-hover:
    backgroundColor: "{colors.shell-raised}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.record}"
    padding: "6px 12px"
  button-secondary-hover:
    backgroundColor: "{colors.ground}"
  input-text:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.record}"
    padding: "8px 12px"
  nav-shell:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-muted}"
    height: "56px"
  nav-link-active:
    textColor: "{colors.shell-ink}"
  share-bar-track:
    backgroundColor: "{colors.ground}"
    height: "12px"
  status-swatch:
    size: "10px"
---

# Design System: CloudVault

## Overview

**Creative North Star: "The Finding Aid"**

CloudVault reads like an archive's finding aid for its own holdings: a summary of what is held and a ruled container list of where it sits, not a wall of metric cards. A slate archive shell sits over a cool box-board ground; content lives on white record panels bounded by hairline rules, with square 2px corners. Public Sans is set like institutional record labels: uppercase tracked captions name each field, and every number is a tabular, lining figure.

The world is light by decision. It is built for a classroom projector, where a pale ground and dark ink survive washed-out projection better than a dark console. Density is moderate: panels breathe, but each row carries a label, a measure and a figure with nothing ornamental between them. Color is mostly slate and grey. Archival green and archival red are reserved for processing outcomes and failures, so they keep their meaning.

The system rejects the four-rounded-cards-and-a-chart console. Summary figures share one ruled strip, and distributions are drawn in place as square-ended bars inside the list rows rather than handed to a chart library.

**Key Characteristics:**
- Slate shell header over a cool box-board ground; white record panels with 1px hairline rules.
- 2px record corners everywhere; no shadows, no gradients.
- Uppercase tracked 12px captions label fields; tabular lining figures everywhere numbers appear.
- Distributions drawn as in-row square-ended bars on one shared scale.
- Green and red mean only success and failure.

## Colors

A cool slate-and-box-board palette with two archival signal colors held in reserve.

### Primary
- **Archive Slate** (shell): the header band and the primary button. It is also the darkest data tone (class-standard), so the most-used class reads as the weightiest bar.
- **Raised Slate** (shell-raised): the outline of the header tag, plus hover on slate surfaces (primary button, log-out button).

### Secondary
- **Box-board Blue-Grey** (accent): the interactive accent. Used for the empty-state icon, input focus rings at 25% opacity, retry-button hover borders and text selection (mixed 28% into white). It is the same value as class-ia, and it marks Pending in processing.
- **Deep Box-board** (accent-strong): focus outlines (2px, offset 2px), the text caret and text links.

### Tertiary
- **Archival Green** (ok): Succeeded processing only.
- **Archival Red** (alert): Failed processing, alert icons and inline form errors. A Failed count above zero switches to semibold red.

### Neutral
- **Record Ink** (ink): headings, figures, primary text.
- **Muted Ink** (ink-muted): captions, subtitles, secondary text, percentages.
- **Faint Ink** (ink-faint): 13px notes and descriptions under figures and class names. Tuned to 5.4:1 on panel and 4.7:1 on ground, so it never drops below 4.5:1.
- **Box-board Ground** (ground): the page background, and the empty track behind share bars.
- **Record White** (panel): every record panel, input and secondary button.
- **Hairline** (rule): panel borders, row dividers, panel-header underlines, and the 1px gaps between strip cells. At 70% opacity it is the skeleton block fill.
- **Strong Hairline** (rule-strong): input and secondary-button borders, scrollbar thumb.
- **Shell Ink / Shell Muted** (shell-ink, shell-muted): active and resting text on the slate shell.

### Data
- **Class Standard / Class IA / Pale Stack Grey** (class-standard, class-ia, class-gir): the three simulated storage classes, from darkest to palest. Pale Stack Grey also marks Skipped in processing.

### Named Rules
**The Reserved Signal Rule.** Archival green means a job succeeded and archival red means one failed or something needs attention. Neither is used for decoration, branding or emphasis.

**The Swatch-Not-Text Rule.** Pale Stack Grey (2.2:1 on white) is only ever a swatch or bar fill. It is never a text color. Every bar it fills sits next to a written figure.

## Typography

**Display Font:** Public Sans Variable (self-hosted via @fontsource-variable/public-sans), with system-ui fallback
**Body Font:** Public Sans Variable
**Label Font:** Public Sans Variable, as uppercase tracked captions

**Character:** A single civic sans used like institutional record labels: plain, firm and legible at projector distance. All hierarchy comes from size, weight and case, never from a second family.

### Hierarchy
- **Display** (600, 34px, tight tracking): the page h1, one per screen. It sits clearly above the figures.
- **Figure** (600, 28px, line-height 1, tabular lining): the summary-strip values and the open-recommendation count.
- **Headline** (600, 20px): the h1 of a standalone card such as the login record.
- **Title** (600, 16px): panel titles in record headers and empty-state titles.
- **Lead** (400, 15px): the single subtitle line under the page h1.
- **Body** (400, 14px): rows, list items, buttons, form text.
- **Note** (400, 13px, ink-faint): the descriptive line under a figure or class name, and disclaimers.
- **Caption** (600, 12px, 0.08em tracking, uppercase, ink-muted): field labels (figure labels, form labels) and right-aligned panel-header asides.

### Named Rules
**The Tabular Figure Rule.** Every number is set in tabular lining figures (tables and any element marked as a figure), so columns of bytes and counts line up.

**The Caption Labels a Field Rule.** A caption names the value directly beneath it or beside it in a header. It is never a free-floating label above a heading.

## Layout

A centered column, max 1152px (max-w-6xl), with 16px side padding (24px from 640px up). The 56px shell header shares that column. Main content starts 32px below the header (40px from 640px up). Vertical sections are 32px apart, and panels within a section have 24px gutters.

The dashboard follows a finding-aid order. First the page heading and a one-line subtitle. Then a ruled summary strip of four figure cells: 2 columns on small screens, 4 from 1024px up, separated by 1px hairline gaps. Below that, a 3-column grid from 1024px up: the container list spans two columns and the side column stacks Processing and Recommendations. Under 1024px everything stacks.

Inside container-list rows, small screens put the label and figures on one line with the bar underneath. From 640px up the columns are fixed: label 13rem, bar flexible, bytes 6rem, share 3.5rem. Figures are right-aligned. Row padding is 16px vertical (10px in compact processing lists). Panel insets are 20px, or 24px from 640px up.

## Elevation & Depth

Flat. There are no shadows and no gradients. Depth comes from three things: the dark slate shell over a pale ground, white panels on the box-board ground, and 1px hairline borders and dividers. The summary strip's cell divisions are the ground-tone rule showing through 1px gaps.

### Named Rules
**The Hairline Not Shadow Rule.** Separate things with a 1px rule or a change of tone, never with a shadow. Surfaces don't lift on hover either.

## Shapes

Square records. Every panel, button, input, tag, skeleton block and focus outline uses the 2px record corner. Bars and status swatches have square ends and no radius. The only dashed border is the empty state's: it shows an unfilled container.

## Components

### Record Panel
The core container: white panel, 1px hairline border, 2px corners. Titled panels get a header row (16px semibold title on the left, optional right-aligned caption aside) underlined by a hairline, and the body sits below. Lists inside panels use hairline row dividers.

### Summary Strip
One record holding four figure cells separated by 1px hairline gaps. Each cell stacks a caption label, a 28px figure and a 13px faint note. It is one ruled strip, never four separate cards.

### Container List (Signature)
Each simulated storage class gets one ruled row: a 10px square swatch with the class name in semibold ink, a faint description, a 12px-tall share bar, right-aligned bytes in medium ink and the share in muted ink. Every bar is drawn at its exact share of all stored bytes, so all rows read on one shared scale. Bars fill a ground-tone track with square ends. No chart library is used on this screen.

### Status List
A compact ruled list: 10px square swatch, label, right-aligned tabular count. Status colors are Pending in accent, Succeeded in ok, Skipped in pale stack grey, Failed in alert. A Failed count above zero becomes semibold red.

### Buttons
- **Shape:** record corner (2px).
- **Primary:** Archive Slate fill, shell-ink text, 14px semibold, 10px 12px padding. Hover changes to Raised Slate. Disabled drops to 60% opacity, and a spinner icon shows while busy.
- **Secondary:** white panel, Strong Hairline border, ink text, 14px medium, 6px 12px padding. Hover moves the border to accent and the fill to ground.
- **Text link:** accent-strong, 14px medium, underlines on hover.
- **Focus:** 2px accent-strong outline, 2px offset (shell-ink outline on the slate header).

### Inputs / Fields
- **Style:** white fill, 1px Strong Hairline border, 2px corners, 8px 12px padding, 14px ink text, caption label 6px above.
- **Focus:** border becomes accent-strong, plus a 2px accent ring at 25% opacity.
- **Error:** an inline 14px alert-red message below the fields, announced as an alert.

### Navigation
A 56px slate shell band. Left: archive icon (lucide, 1.75 stroke, shell-muted), "CloudVault" wordmark in 15px semibold, and an outlined uppercase "Simulated S3" tag. Nav links are 14px medium in shell-muted. The active link turns shell-ink with a 2px shell-ink bottom rule; hover turns shell-ink. Right: the account email, then a ghost log-out button that fills Raised Slate on hover. On mobile the email and button label hide and the nav scrolls horizontally.

### States
- **Loading:** static skeleton blocks (hairline at 70%, 2px corners) that mirror the loaded layout (strip, container list, two stacked panels), so nothing shifts when data arrives. No shimmer.
- **Empty:** a dashed record with a 32px accent archive icon, a 16px title and a muted explanation.
- **Error:** a record with a red alert icon, title, muted message and a secondary Retry button whose icon spins while retrying.

## Do's and Don'ts

### Do:
- **Do** put content on white record panels with a 1px hairline border and 2px corners.
- **Do** label every figure with a 12px uppercase tracked caption and set the figure in tabular lining numerals.
- **Do** draw distributions as square-ended in-row bars on one shared scale, each next to its written figure.
- **Do** keep notes at 13px in Faint Ink (at least 4.5:1 on panel and ground).
- **Do** make skeletons mirror the loaded layout.
- **Do** keep the world light; it is set for projection.

### Don't:
- **Don't** use shadows or gradients; separate with hairlines and tone.
- **Don't** split summary figures into separate rounded metric cards.
- **Don't** use archival green or red for anything but success and failure.
- **Don't** set text in Pale Stack Grey.
- **Don't** round corners beyond the 2px record corner, or round the ends of bars and swatches.
- **Don't** float a caption above a heading as a kicker or eyebrow.
