// What jsdom leaves out and the app calls: the router scrolls a new page to its
// top, the tree a row the keys moved to into sight. Not in the tests that run in
// node (the build's), which have no window.
if (typeof window !== "undefined") {
  window.scrollTo = () => undefined;
  Element.prototype.scrollIntoView = () => undefined;
}
