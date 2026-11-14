/**
 * A file the page fetched, saved under its name: fetched with the session's token - a link to an /api
 * address would carry none - then offered through a link that is gone again at once, its address freed
 * even where the click fails.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const address = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = address;
  link.download = filename;
  link.hidden = true;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(address);
  }
}
