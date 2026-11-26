// What jsdom leaves out and the app calls: the router scrolls a new page to its
// top, the tree a row the keys moved to into sight, a scrolling box hears its
// size change; axe asks a canvas for its context, which jsdom draws none of and says so on every run - null, as a
// browser answers a context it cannot give. Not in the tests that run in node (the build's), which have no window.
if (typeof window !== "undefined") {
  window.scrollTo = () => undefined;
  Element.prototype.scrollIntoView = () => undefined;
  HTMLCanvasElement.prototype.getContext = () => null;
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}
