import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { saveBlob } from "@/download";

let clicked: { name: string; href: string; inPage: boolean }[] = [];
let click: MockInstance<() => void>;
const created = vi.fn(() => "blob:made");
const freed = vi.fn();

beforeEach(() => {
  clicked = [];
  created.mockClear();
  freed.mockClear();
  // jsdom has no object URLs, and follows no link
  URL.createObjectURL = created;
  URL.revokeObjectURL = freed;
  click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ name: this.download, href: this.href, inPage: document.body.contains(this) });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("saving a file the page fetched", () => {
  it("offers it under its name through a link that leaves no trace", () => {
    const blob = new Blob(["x"], { type: "text/turtle" });

    saveBlob(blob, "mem-d1.ttl");

    expect(created).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([{ name: "mem-d1.ttl", href: "blob:made", inPage: true }]);
    expect(document.querySelector("a[download]")).toBeNull();
    expect(freed).toHaveBeenCalledWith("blob:made");
  });

  it("frees the address even where the click fails", () => {
    click.mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(() => saveBlob(new Blob(["x"]), "mem-d1.ttl")).toThrow("blocked");
    expect(freed).toHaveBeenCalledWith("blob:made");
    expect(document.querySelector("a[download]")).toBeNull();
  });
});
