import type { SelectionSource } from "./SelectedInstrumentProvider";

export const LOCATION_CHANGE_EVENT = "qibao:locationchange";

export function commitLocation(url: string, source?: SelectionSource): void {
  window.history.pushState({}, "", url);
  window.dispatchEvent(new CustomEvent(LOCATION_CHANGE_EVENT, { detail: { source } }));
}
