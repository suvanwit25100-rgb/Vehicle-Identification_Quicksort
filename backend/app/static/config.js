/* Where video uploads go. Empty means the same address as this page, which is right when one server serves everything.
   When the pages are hosted separately from the API (for example on Vercel), set it to the API's address, e.g. "https://exlex-api.onrender.com",
   because a proxy in front of the pages cannot carry large video uploads. deploy/set_backend.py does this for you. */
window.EXLEX = { uploadBase: "" };
