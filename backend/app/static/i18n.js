"use strict";
/* Hindi and English. English is the page as written; when Hindi is chosen, every piece of text that matches an entry below is swapped, including
   text the page's scripts add later. Text with no entry stays in English, so nothing is ever blank. Covered: the menu, the landing hero, the report
   a problem pages and the track a report page. The choice is remembered in this browser. Hindi wording should be read by a native speaker before use. */
(function () {
  const KEY = "exlex-lang";
  let lang = "en";
  try { lang = localStorage.getItem(KEY) || (/^hi\b/i.test(navigator.language || "") ? "hi" : "en"); } catch (e) { /* storage blocked */ }
  if (lang !== "hi") lang = "en";

  const HI = {
    /* menu and footer */
    "Overview": "मुख्य पृष्ठ", "Features": "सुविधाएँ", "Console": "कंसोल", "Monitor": "निगरानी", "Archive": "अभिलेख", "Report an issue": "शिकायत दर्ज करें",
    "Officer portal": "अधिकारी पोर्टल", "MENU": "मेनू", "CLOSE": "बंद करें",
    "ExLex · AIML-01 · Vehicle identification and traceability from CCTV footage. © 2026 Team Quicksort.": "ExLex · AIML-01 · सीसीटीवी फुटेज से वाहन की पहचान और ट्रेसबिलिटी। © 2026 Team Quicksort।",
    "Confidence scores are uncalibrated estimates. Candidates are leads for an investigator to verify, not identifications. Characters that cannot be read are shown as ? and are never guessed.":
      "विश्वास-अंक अंशांकित अनुमान नहीं, मोटे अनुमान हैं। उम्मीदवार जाँचकर्ता के सत्यापन के लिए सुराग हैं, पहचान नहीं। जो अक्षर पढ़े नहीं जा सकते उन्हें ? दिखाया जाता है और अंदाज़े से कभी नहीं भरा जाता।",
    /* agencies */
    "Police": "पुलिस", "Ministry of Road Transport and Highways / NHAI": "सड़क परिवहन एवं राजमार्ग मंत्रालय / NHAI", "Border Security Force": "सीमा सुरक्षा बल",
    "Sashastra Seema Bal": "सशस्त्र सीमा बल", "Customs": "सीमा शुल्क",
    /* landing hero */
    "AIML-01 · Problem statement": "AIML-01 · समस्या कथन", "Problem": "समस्या", ": Vehicle Identification and Traceability": ": वाहन की पहचान और ट्रेसबिलिटी",
    "Source": "स्रोत", ": CCTV footage, any quality": ": सीसीटीवी फुटेज, किसी भी गुणवत्ता का", "Users": "उपयोगकर्ता",
    ": Police · MoRTH / NHAI · BSF · SSB · Customs": ": पुलिस · MoRTH / NHAI · BSF · SSB · सीमा शुल्क",
    "© 2026 Team Quicksort, all rights reserved.": "© 2026 Team Quicksort, सर्वाधिकार सुरक्षित।",
    "Read what the camera saw.": "कैमरे ने जो देखा, वह पढ़ें।", "Say what it did not.": "जो नहीं देखा, उसे साफ़ कहें।",
    "A blurry frame in. A ranked, explained shortlist out. Where the footage is silent, the system says so instead of guessing.":
      "धुंधली फ़्रेम अंदर, क्रमबद्ध और समझाई गई सूची बाहर। जहाँ फ़ुटेज कुछ नहीं बताती, वहाँ सिस्टम अंदाज़ा लगाने के बजाय साफ़ कह देता है।",
    "Open the console": "कंसोल खोलें", "Watch it work": "इसे काम करते देखें", "Scroll": "नीचे जाएँ",
    /* report a problem */
    "Citizen reports": "नागरिक शिकायतें", "Report a vehicle.": "वाहन की शिकायत करें।", "It takes a minute.": "इसमें बस एक मिनट लगता है।",
    "Photograph the vehicle. We read the plate, you check it, and the report goes to the department that handles it. A report is a lead for an officer to review, not a verdict on anyone.":
      "वाहन की फ़ोटो लें। हम नंबर प्लेट पढ़ते हैं, आप उसे जाँचते हैं, और शिकायत उस विभाग तक पहुँचती है जो इसे देखता है। शिकायत अधिकारी के जाँचने के लिए एक सुराग है, किसी के बारे में फ़ैसला नहीं।",
    "Progress": "प्रगति", "Photo": "फ़ोटो", "Check the plate": "प्लेट जाँचें", "Details": "विवरण", "Done": "पूरा",
    "1 · Photograph the vehicle": "1 · वाहन की फ़ोटो लें", "Take a photo or choose one": "फ़ोटो खींचें या चुनें",
    "Get the whole back or front of the vehicle in view, with the number plate visible. JPEG, PNG or WebP, up to 10 MB.": "वाहन का पूरा पिछला या अगला हिस्सा फ़्रेम में रखें, नंबर प्लेट दिखती हो। JPEG, PNG या WebP, 10 MB तक।",
    "Use the camera": "कैमरा इस्तेमाल करें",
    "2 · Check the plate we read": "2 · हमने जो प्लेट पढ़ी, उसे जाँचें", "What the system read": "सिस्टम ने क्या पढ़ा", "Your photo": "आपकी फ़ोटो", "Plate found in the photo": "फ़ोटो में मिली प्लेट",
    "Plate as you can see it (optional)": "प्लेट जैसी आपको दिखती है (वैकल्पिक)",
    "Fill this in only if you can read the plate in your photo. Letters and digits only, spaces are fine. Leave it empty if you cannot see it.":
      "इसे तभी भरें जब आप अपनी फ़ोटो में प्लेट पढ़ पा रहे हों। केवल अक्षर और अंक, खाली जगह चलेगी। न दिखे तो खाली छोड़ दें।",
    "Use the system's read": "सिस्टम का पढ़ा हुआ इस्तेमाल करें", "Back": "पीछे", "Continue": "आगे बढ़ें",
    "3 · What happened": "3 · क्या हुआ", "What are you reporting?": "आप किस बात की शिकायत कर रहे हैं?", "Choose one…": "एक चुनें…", "What did you see?": "आपने क्या देखा?",
    "For example: this vehicle jumped the red light at the junction and nearly hit a pedestrian.": "उदाहरण: इस वाहन ने चौराहे पर लाल बत्ती पार की और एक पैदल यात्री को लगभग टक्कर मार दी।",
    "/ 1000. Describe the vehicle and what it did, not who you think is driving.": "/ 1000. वाहन और उसने क्या किया, यह बताएँ; यह नहीं कि आपके हिसाब से कौन चला रहा है।",
    "Where?": "कहाँ?", "Road, landmark, city": "सड़क, पहचान की जगह, शहर", "When?": "कब?", "Use my current location": "मेरी मौजूदा जगह इस्तेमाल करें",
    "Contact (optional)": "संपर्क (वैकल्पिक)", "Phone or email, only if an officer may call you": "फ़ोन या ईमेल, केवल तभी जब अधिकारी आपसे संपर्क कर सकें",
    "Seen only by officers. Leave empty to stay anonymous.": "केवल अधिकारी देखते हैं। गुमनाम रहने के लिए खाली छोड़ें।",
    "I took this photo, what I wrote is true as far as I know, and I agree that the photo, plate, location and time are stored and seen by officers of the department that handles this report. I understand a false report can harm someone.":
      "यह फ़ोटो मैंने खींची है, मैंने जो लिखा वह मेरी जानकारी में सच है, और मैं सहमत हूँ कि फ़ोटो, प्लेट, जगह और समय सुरक्षित रखे जाएँगे और इस शिकायत को देखने वाले विभाग के अधिकारी इन्हें देखेंगे। मैं समझता/समझती हूँ कि झूठी शिकायत किसी को नुकसान पहुँचा सकती है।",
    "Send report": "शिकायत भेजें", "4 · Report received": "4 · शिकायत मिल गई",
    "Keep this ID. You can check the state of your report below at any time. You will not be shown owner or registry details: only officers can see those.":
      "यह आईडी संभालकर रखें। आप नीचे कभी भी अपनी शिकायत की स्थिति देख सकते हैं। मालिक या रजिस्ट्री की जानकारी आपको नहीं दिखाई जाएगी: उसे केवल अधिकारी देख सकते हैं।",
    "Track this report": "इस शिकायत को ट्रैक करें", "Report another": "एक और शिकायत करें", "Check a report": "शिकायत की स्थिति देखें", "Report ID": "शिकायत आईडी",
    "12-character report ID": "12 अक्षरों की शिकायत आईडी", "Check": "देखें", "What happens to your report": "आपकी शिकायत का क्या होता है",
    "The photo, plate, place and time go to officers of the department that handles this kind of report. Nobody else sees them.": "फ़ोटो, प्लेट, जगह और समय उस विभाग के अधिकारियों तक जाते हैं जो इस तरह की शिकायत देखता है। और कोई इन्हें नहीं देखता।",
    "Owner details are never shown to you or to anyone who is not an officer.": "मालिक की जानकारी आपको या किसी ऐसे व्यक्ति को कभी नहीं दिखाई जाती जो अधिकारी नहीं है।",
    "Time and place hidden in a photo are only suggested to you. You decide what to send.": "फ़ोटो में छिपे समय और जगह केवल सुझाव के रूप में दिखाए जाते हैं। क्या भेजना है, यह आप तय करते हैं।",
    "Please photograph the vehicle, not people. Do not follow or confront anyone.": "कृपया वाहन की फ़ोटो लें, लोगों की नहीं। किसी का पीछा न करें और किसी से टकराव न करें।",
    "This is a demonstration build. Do not use it for an emergency: call 112.": "यह एक प्रदर्शन संस्करण है। आपात स्थिति में इसका उपयोग न करें: 112 पर कॉल करें।",
    /* messages from the report page */
    "Asking for your location…": "आपकी जगह पूछी जा रही है…", "Choose what you are reporting.": "चुनें कि आप किसकी शिकायत कर रहे हैं।",
    "Describe what you saw (at least a few words).": "बताएँ आपने क्या देखा (कम से कम कुछ शब्द)।", "Location was not shared. Type the place instead.": "जगह साझा नहीं की गई। उसकी जगह स्थान लिखें।",
    "No report with that ID.": "इस आईडी की कोई शिकायत नहीं मिली।", "Please tick the box to confirm and agree.": "पुष्टि और सहमति के लिए बॉक्स पर निशान लगाएँ।",
    "Say where it happened.": "बताएँ यह कहाँ हुआ।", "That is not an image. Choose a photo.": "यह फ़ोटो नहीं है। कोई फ़ोटो चुनें।",
    "That photo is over 10 MB. Choose a smaller one.": "यह फ़ोटो 10 MB से बड़ी है। कोई छोटी फ़ोटो चुनें।",
    "The plate must be 4 to 10 letters or digits. Leave it empty if you cannot read it.": "प्लेट में 4 से 10 अक्षर या अंक होने चाहिए। पढ़ न पाएँ तो खाली छोड़ दें।",
    "This device cannot share a location.": "यह उपकरण जगह साझा नहीं कर सकता।", "Reading the plate…": "प्लेट पढ़ी जा रही है…", "Sending…": "भेजा जा रहा है…",
    /* categories */
    "Traffic violation (signal, wrong side, helmet, seat belt)": "यातायात उल्लंघन (सिग्नल, गलत दिशा, हेलमेट, सीट बेल्ट)",
    "Reckless or dangerous driving": "लापरवाही या ख़तरनाक ढंग से गाड़ी चलाना", "Hit-and-run or accident": "टक्कर मारकर भागना या दुर्घटना",
    "Suspicious or abandoned vehicle": "संदिग्ध या लावारिस वाहन", "Number plate looks fake, missing or tampered with": "नंबर प्लेट नकली, गायब या छेड़छाड़ की हुई लगती है",
    "Suspicious vehicle near the western or eastern border": "पश्चिमी या पूर्वी सीमा के पास संदिग्ध वाहन", "Suspicious vehicle near the Nepal or Bhutan border": "नेपाल या भूटान सीमा के पास संदिग्ध वाहन",
    "Suspected smuggling or contraband movement": "तस्करी या प्रतिबंधित सामान की आवाजाही का संदेह",
    /* statuses */
    "New": "नई", "Under review": "जाँच में", "Verified": "सत्यापित", "Forwarded": "आगे भेजी गई", "Closed": "बंद", "Rejected": "अस्वीकृत",
    /* track a report */
    "Track a report": "शिकायत ट्रैक करें", "Where is my report?": "मेरी शिकायत कहाँ है?", "In plain words.": "सीधे शब्दों में।",
    "Enter the 12-character ID you were given when you filed it. You will see what has happened so far. You will never see officer notes, owner details or anyone's plate here.":
      "शिकायत दर्ज करते समय मिली 12 अक्षरों की आईडी डालें। अब तक क्या हुआ, यह आपको दिखेगा। यहाँ अधिकारियों के नोट, मालिक की जानकारी या किसी की प्लेट कभी नहीं दिखाई जाती।",
    "Show my report": "मेरी शिकायत दिखाएँ", "e.g. 4f3f7be6c9f9": "जैसे 4f3f7be6c9f9", "About": "विषय", "Handled by": "किसके पास है", "Filed": "दर्ज हुई", "Last change": "आख़िरी बदलाव",
    "What has happened": "अब तक क्या हुआ", "Received": "मिल गई", "Being looked at": "देखी जा रही है", "Checked": "जाँची गई", "Passed on": "आगे भेजी गई", "Finished": "पूरी हुई", "Reviewed, no action": "जाँची गई, कोई कार्रवाई नहीं",
    "We have your report. An officer has not looked at it yet.": "हमें आपकी शिकायत मिल गई है। किसी अधिकारी ने अभी इसे नहीं देखा है।",
    "An officer is reviewing your report and the evidence in it.": "एक अधिकारी आपकी शिकायत और उसके सबूत देख रहे हैं।",
    "An officer checked the evidence and found it worth acting on.": "एक अधिकारी ने सबूत जाँचे और कार्रवाई के लायक पाया।",
    "Your report was passed to the agency that handles this.": "आपकी शिकायत उस एजेंसी को भेज दी गई जो इसे देखती है।",
    "The agency has finished with this report.": "एजेंसी इस शिकायत पर अपना काम पूरा कर चुकी है।",
    "An officer reviewed it and no action will be taken, for example because it could not be checked. This is not a judgement about you.":
      "एक अधिकारी ने इसे देखा और कोई कार्रवाई नहीं होगी, जैसे कि इसे जाँचा नहीं जा सका। यह आपके बारे में कोई निर्णय नहीं है।",
    "You filed this report.": "आपने यह शिकायत दर्ज की।", "An officer took your report.": "एक अधिकारी ने आपकी शिकायत ली।", "Your report is waiting for an officer.": "आपकी शिकायत किसी अधिकारी के इंतज़ार में है।",
    "Status changed to “Received”.": "स्थिति बदलकर “मिल गई” हुई।", "Status changed to “Being looked at”.": "स्थिति बदलकर “देखी जा रही है” हुई।", "Status changed to “Checked”.": "स्थिति बदलकर “जाँची गई” हुई।",
    "Status changed to “Passed on”.": "स्थिति बदलकर “आगे भेजी गई” हुई।", "Status changed to “Finished”.": "स्थिति बदलकर “पूरी हुई” हुई।", "Status changed to “Reviewed, no action”.": "स्थिति बदलकर “जाँची गई, कोई कार्रवाई नहीं” हुई।",
    "Your report is a lead for an officer to check, not a verdict on anyone. Owner and registry details are never shown here.": "आपकी शिकायत अधिकारी के जाँचने के लिए एक सुराग है, किसी के बारे में फ़ैसला नहीं। मालिक और रजिस्ट्री की जानकारी यहाँ कभी नहीं दिखाई जाती।",
    "No report with that ID. Check it for a typing mistake.": "इस आईडी की कोई शिकायत नहीं मिली। टाइप करने में गलती तो नहीं हुई, जाँचें।",
  };
  const ATTRS = ["placeholder", "aria-label", "title", "alt"];
  const norm = (s) => s.replace(/\s+/g, " ").trim();

  function swapText(node) {
    const t = norm(node.nodeValue);
    if (t && HI[t] !== undefined) node.nodeValue = node.nodeValue.replace(/\S[\s\S]*\S|\S/, HI[t]);
  }
  function swapAttrs(el) {
    for (const a of ATTRS) { const v = el.getAttribute && el.getAttribute(a); if (v && HI[norm(v)] !== undefined) el.setAttribute(a, HI[norm(v)]); }
  }
  function walk(root) {
    if (root.nodeType === 3) return swapText(root);
    if (root.nodeType !== 1 || /^(SCRIPT|STYLE|PRE|CODE|TEXTAREA)$/.test(root.tagName)) { if (root.tagName === "TEXTAREA") swapAttrs(root); return; }
    swapAttrs(root);
    for (const kid of root.childNodes) walk(kid);
  }

  function button() {
    const b = document.createElement("button");
    b.type = "button"; b.className = "lang-btn";
    b.textContent = lang === "hi" ? "EN" : "हिं";
    b.setAttribute("aria-label", lang === "hi" ? "Switch to English" : "हिन्दी में बदलें");
    b.addEventListener("click", () => { api.set(lang === "hi" ? "en" : "hi"); });
    return b;
  }
  const api = {
    get lang() { return lang; },
    button,
    set(l) { try { localStorage.setItem(KEY, l); } catch (e) { /* storage blocked: the choice lasts only until reload */ } location.reload(); },
    t: (en) => (lang === "hi" && HI[norm(en)] !== undefined ? HI[norm(en)] : en),
  };
  window.I18N = api;
  document.documentElement.lang = lang;
  if (lang !== "hi") return;

  const font = document.createElement("link");
  font.rel = "stylesheet"; font.href = "https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@300;400;500;600;700&display=swap";
  document.head.append(font);
  const start = () => {
    walk(document.body);
    new MutationObserver((muts) => muts.forEach((m) => {
      if (m.type === "characterData") swapText(m.target);
      else if (m.type === "attributes") swapAttrs(m.target);
      else m.addedNodes.forEach(walk);
    })).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();
