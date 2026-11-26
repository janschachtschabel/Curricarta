// All user-facing strings live here behind semantic keys. A single-locale
// catalogue with its own t() keeps the strings external, so a second locale is
// mechanical work; tests/i18n-catalogue.test.ts keeps every key in use.
// simplify: one locale and two plural slots (one/other); a locale with more
// plural categories - Polish has four - needs vue-i18n or a third slot.
export const messages = {
  app: {
    title: "Curricarta",
    // The way past the header for someone arriving by keyboard.
    skipToContent: "Zum Inhalt springen",
    nav: {
      // Names the landmark, so a screen reader can list it and jump to it by name.
      label: "Hauptnavigation",
      start: "Start",
      sources: "Quellen",
      lexicon: "Lexikon",
    },
    // What each page is called in the browser's title bar, its tabs and
    // bookmarks - and what a screen reader announces on arrival.
    titles: {
      start: "Start",
      login: "Anmeldung",
      sources: "Quellen",
      source: "Registereintrag",
      conversion: "Blöcke",
      document: "Dokument",
      documentTree: "Baum des Dokuments",
      lexicon: "Lexikon prüfen",
    },
    roles: {
      admin: "Administration",
      redaktion: "Redaktion",
      nutzer: "Nutzung",
    },
    roleList: "Rollen: {roles}",
    signedInAs: "Angemeldet als",
    signIn: "Anmelden",
    signOut: "Abmelden",
    // in the shell, a token held whose account did not load (App.vue)
    accountFailed: "Dein Konto wurde nicht geladen.",
    // said once a retry in the shell loaded it
    accountLoaded: "Dein Konto ist geladen.",
  },
  // one convention in every form: a required field says so in its label, a free one says nothing (formWords.ts)
  forms: {
    required: "{label} (Pflichtfeld)",
    // a field's problem, said where the keyboard stayed elsewhere (ImportForm.vue, UploadForm.vue)
    fieldProblem: "{field}: {problem}",
  },
  login: {
    heading: "Anmeldung",
    intro: "Gib das Zugangstoken ein, das dir die Administration gegeben hat.",
    // reached while signed in (LoginView.vue)
    signedIn: "Du bist schon als {name} angemeldet. Mit einem anderen Zugangstoken meldest du dich als anderes Konto an.",
    toStart: "Zur Startseite",
    tokenLabel: "Zugangstoken",
    submit: "Anmelden",
    checking: "Wird geprüft …",
    errors: {
      empty: "Gib ein Zugangstoken ein.",
      malformed: "Das ist kein Zugangstoken: Es beginnt mit curricarta_ und hat danach 43 Zeichen.",
      invalid: "Dieses Zugangstoken gilt nicht. Prüfe es, oder bitte die Administration um ein neues.",
      network: "Der Server ist nicht erreichbar. Versuch es gleich noch einmal.",
      server: "Der Server hat unerwartet geantwortet. Versuch es später noch einmal.",
      locked:
        "Zu viele fehlgeschlagene Anmeldungen von dieser Adresse. " +
        "Versuch es in {count} {count|Minute|Minuten} noch einmal.",
      lockedLater: "Zu viele fehlgeschlagene Anmeldungen von dieser Adresse. Versuch es später noch einmal.",
    },
  },
  start: {
    welcome: "Willkommen, {name}",
    intro:
      "Hier entsteht die Wissenslandkarte der Lehrpläne: erfassen, an Kompetenz- und " +
      "Niveauschemata andocken, vernetzen. Unter „Quellen“ legst du die Lehrplandokumente an; " +
      "weitere Werkzeuge folgen.",
    toSources: "Zu den Quellen",
    about: "Curricarta erfasst Lehrpläne aller Bildungsbereiche und verbindet sie zu einer Wissenslandkarte.",
    // What PUBLIC_ACCESS opens to a visitor without an account.
    visitor: {
      off: "Ohne Konto ist noch nichts offen. Melde dich mit deinem Zugangstoken an.",
      lookup: "Nachschlagen ist auch ohne Konto offen. Für alles andere meldest du dich an.",
      search: "Nachschlagen und Suchen sind auch ohne Konto offen. Für alles andere meldest du dich an.",
    },
    signIn: "Zur Anmeldung",
    infoFailed: "Die Startseite konnte nicht geladen werden.",
    accountFailed: "Dein Konto konnte nicht geladen werden.",
    // A 429 on the account: only a refused token meets the address's lock.
    accountRejected:
      "Das gespeicherte Zugangstoken gilt nicht mehr. " +
      "Melde dich ab und mit einem gültigen Zugangstoken neu an.",
  },
  // The source register: the curriculum documents and what may be done with them.
  sources: {
    heading: "Quellen",
    // an entry with neither title, address nor file (registerWords.ts entryName)
    untitled: "Eintrag ohne Titel",
    intro:
      "Das Register der Lehrplandokumente: was hochgeladen oder von einer Adresse abgerufen " +
      "wurde, wie weit es ist und unter welchen Rechten es steht.",
    addHeading: "Dokument hinzufügen",
    upload: {
      heading: "Datei hochladen",
      fileLabel: "Datei",
      fileHint: "PDF, Word (DOCX), RTF, HTML, Markdown, Text (UTF-8) oder Turtle, bis {limit} MB.",
      // where the limit did not load: the server still says it on a refusal
      fileHintNoLimit: "PDF, Word (DOCX), RTF, HTML, Markdown, Text (UTF-8) oder Turtle.",
      titleLabel: "Titel",
      titleHint: "Ohne Titel trägt der Eintrag den Namen der Datei.",
      submit: "Hochladen",
      busy: "Wird hochgeladen …",
      done: "„{title}“ steht jetzt im Register.",
      failed: "Die Datei wurde nicht hochgeladen.",
      errors: {
        missing: "Wähle eine Datei aus.",
        tooLarge: "Die Datei ist größer als {limit} MB. Verkleinere sie oder teile sie auf.",
      },
    },
    import: {
      heading: "Von einer Adresse abrufen",
      urlLabel: "Adresse (URL)",
      urlHint: "Der Server lädt das Dokument selbst herunter; das dauert meist nur einige Sekunden.",
      titleLabel: "Titel",
      titleHint: "Ohne Titel trägt der Eintrag den Namen der Datei unter der Adresse.",
      submit: "Abrufen",
      busy: "Wird gestartet …",
      started: "Der Abruf von „{title}“ läuft.",
      failed: "Der Abruf wurde nicht gestartet.",
      errors: {
        missing: "Gib eine Adresse ein.",
        scheme: "Das ist keine Webadresse. Eine Webadresse beginnt mit https:// oder http://.",
        spaces: "Die Adresse enthält Leerzeichen. Kopiere sie noch einmal aus der Adresszeile des Browsers.",
        tooLong:
          "Die Adresse ist länger als {limit} {limit|Zeichen|Zeichen}. Nimm die Adresse des Dokuments selbst, oft ohne den Teil " +
          "nach dem Fragezeichen.",
        credentials:
          "Die Adresse enthält einen Namen oder ein Kennwort. Der Server ruft nur frei zugängliche Adressen ab: " +
          "Lade die Datei stattdessen hoch.",
      },
    },
    jobs: {
      // the fetches and checks started on the page
      heading: "Aufträge",
    },
    // The check of the seed, an admin's (CheckStart.vue)
    check: {
      heading: "Saat prüfen",
      intro:
        "Fragt die Adresse jedes Kandidaten einmal ab: ob sie erreichbar ist, was dort liegt und wie groß es ist. " +
        "Gespeichert wird nur das Ergebnis. Die Prüfung beachtet robots.txt, fragt jeden Server höchstens alle " +
        "paar Sekunden und umgeht keine Sperre; bei vielen Adressen dauert sie eine Stunde und länger.",
      start: "Prüfung starten",
      confirmTitle: "Prüfung der Saat starten?",
      confirmMessage:
        "Der Server fragt jetzt die Adressen aller Kandidaten bei fremden Servern ab. Die Prüfung läuft im " +
        "Hintergrund weiter, auch wenn du die Seite verlässt; eine spätere Prüfung fragt nur, was noch offen ist.",
      confirm: "Prüfung starten",
      // an event, not a state: the line stays once the check has ended
      started: "Die Prüfung wurde gestartet; wie weit sie ist, zeigt die Liste der Aufträge.",
      running: "Eine Prüfung lief schon; wie weit sie ist, zeigt die Liste der Aufträge.",
      failed: "Die Prüfung wurde nicht gestartet.",
      jobLabel: "Prüfung der Saat",
    },
    register: {
      heading: "Register",
      columns: {
        title: "Titel",
        provenance: "Herkunft",
        status: "Stand",
        rights: "Rechte",
        added: "Hinzugefügt",
      },
      // Names the box that scrolls the table on a narrow screen, for whoever reaches it by keyboard.
      scrollLabel: "Registertabelle",
      noFile: "noch keine Datei",
      mine: "von dir",
      emptyTitle: "Noch keine Quellen",
      emptyBody: "Lade oben eine Datei hoch oder gib eine Adresse an. Der Eintrag erscheint dann hier.",
      loadFailed: "Das Register wurde nicht geladen.",
      shown: "{shown} von {total} {total|Eintrag|Einträgen}",
      more: "Weitere laden",
      moreFailed: "Weitere Einträge wurden nicht geladen.",
      reloadFailed: "Das Register wurde nicht neu geladen; es zeigt den Stand von vorher.",
      // Beside the heading while what the register shows is read again (SourcesView.vue)
      reading: "Wird neu geladen …",
    },
    // What the register shows (RegisterFilter.vue)
    filter: {
      legend: "Anzeigen",
      candidates: "Nur Kandidaten",
      candidatesHint:
        "Einträge aus Vergleichsdatensatz und Länderrecherche, deren Datei noch fehlt – das, was die " +
        "Prüfung der Saat ansieht.",
      status: "Stand",
      anyStatus: "jeder Stand",
      // in the title or the address, sent with its button or Enter
      search: "Titel oder Adresse durchsuchen",
      searchButton: "Suchen",
      country: "Land",
      anyCountry: "jedes Land",
      none: "Kein Eintrag passt zu diesem Filter.",
      emptyTitle: "Kein Eintrag passt",
      // by what is set; {label} is the checkbox's own label, {any} the status list's first choice
      emptyBody: {
        candidates: "Nimm „{label}“ zurück, um alle Einträge zu sehen.",
        status: "Wähle einen anderen Stand oder „{any}“.",
        both: "Nimm „{label}“ zurück oder wähle einen anderen Stand.",
        search: "Ändere die Suche oder das Land, oder nimm sie zurück.",
      },
    },
    // Where an entry comes from (backend app/sources/register.py, Provenance). Read
    // as messages.sources.provenance[value], not by t(): a value holds a dot.
    provenance: {
      upload: "Upload",
      url: "Adresse",
      "vergleichsdatensatz-v62.493": "Vergleichsdatensatz",
      laenderrecherche: "Länderrecherche",
      ttl: "Turtle-Import",
      recherche: "Recherche",
      redaktion: "Redaktion",
    },
    // How far the register has come with it (RegisterStatus)
    status: {
      unchecked: "ungeprüft",
      reachable: "erreichbar",
      unreachable: "nicht erreichbar",
      acquired: "Datei liegt vor",
    },
    // On what terms it may be used (RightsStatus)
    rights: {
      amtlich: "amtliches Werk",
      offen_lizenziert: "offen lizenziert",
      geschuetzt: "geschützt",
      unklar: "ungeklärt",
    },
    // Whose curriculum it is, by the code of ISO 3166-2:DE the seeds give. Read as
    // messages.sources.countries[value], not by t(): a code holds a hyphen.
    countries: {
      DE: "Bund",
      "DE-BB": "Brandenburg",
      "DE-BE": "Berlin",
      "DE-BW": "Baden-Württemberg",
      "DE-BY": "Bayern",
      "DE-HB": "Bremen",
      "DE-HE": "Hessen",
      "DE-HH": "Hamburg",
      "DE-MV": "Mecklenburg-Vorpommern",
      "DE-NI": "Niedersachsen",
      "DE-NW": "Nordrhein-Westfalen",
      "DE-RP": "Rheinland-Pfalz",
      "DE-SH": "Schleswig-Holstein",
      "DE-SL": "Saarland",
      "DE-SN": "Sachsen",
      "DE-ST": "Sachsen-Anhalt",
      "DE-TH": "Thüringen",
    },
  },
  // One register entry's page (SourceDetailView.vue)
  entryPage: {
    // the page's heading until the entry names it
    heading: "Registereintrag",
    back: "Zurück zum Register",
    // a seed's candidate without its file: no route fetches or checks one entry (backend app/api/source_checks.py)
    candidateNext:
      "Eine Datei holt die Anwendung für diesen Kandidaten nicht. Ob seine Adresse erreichbar ist, prüft die " +
      "Administration für alle Kandidaten zugleich im Register („Saat prüfen“). Willst du mit dem Dokument " +
      "arbeiten, lade es im Register hoch oder gib dort seine Adresse an – daraus entsteht ein eigener Eintrag.",
    loadFailed: "Der Eintrag wurde nicht geladen.",
    notFoundTitle: "Diesen Eintrag gibt es nicht",
    notFoundBody: "Oder dein Konto sieht ihn nicht. Das Register zeigt alle Einträge, die du sehen darfst.",
    facts: {
      heading: "Eintrag",
      provenance: "Herkunft",
      status: "Stand",
      rights: "Rechte",
      license: "Lizenz",
      rightsEvidence: "Rechtebeleg",
      sourceType: "Art der Quelle",
      country: "Land",
      address: "Adresse",
      file: "Datei",
    },
    // How the entry's file came into the register, each time it came (Acquisition)
    acquisitions: {
      heading: "Erwerb der Datei",
      method: "Art",
      acquiredAt: "Zeitpunkt",
      receivedName: "Angekommen als",
      // the address asked first, then each one it led on to
      chain: "Adressen des Abrufs",
    },
    acquisitionMethod: {
      upload: "hochgeladen",
      url: "von einer Adresse abgerufen",
    },
    // Who publishes the copy (SourceType)
    sourceType: {
      amtlich: "amtliche Stelle",
      archiv: "Archivkopie",
      spiegel: "Spiegel, gekennzeichnet",
      sekundaer: "Sekundärquelle",
    },
    seed: {
      heading: "Aus der Saat",
      dataset: "Datensatz",
      schoolForm: "Schulform",
      stage: "Bildungsstufe",
      subject: "Fach",
      grades: "Jahrgänge",
      gradeRange: "{from}–{to}",
      binding: "Verbindlichkeit",
      archive: "Archivkopie",
      archiveOpen: "Archivkopie öffnen",
      evidence: "Beleg",
    },
    // Where a land's research read the row (Evidence)
    evidence: {
      E: "im Dokument selbst gefunden",
      S: "aus einer zweiten Quelle",
    },
    check: {
      heading: "Prüfung der Adresse",
      none: "Die Adresse wurde noch nicht geprüft.",
      outcome: "Ergebnis",
      statusCode: "Antwort des Servers",
      kind: "Art der Datei",
      size: "Größe",
      checkedAt: "Geprüft",
    },
    // What the check found (CheckOutcome)
    outcome: {
      reachable: "erreichbar",
      too_large: "erreichbar, aber größer, als ein Upload sein darf",
      refused: "vom Server verweigert",
      throttled: "der Server bat um eine Pause; eine spätere Prüfung fragt noch einmal",
      server_error: "Fehler beim Server",
      unavailable: "gerade nicht erreichbar; eine spätere Prüfung fragt noch einmal",
      unreachable: "nicht erreichbar",
      robots: "laut robots.txt nicht abzurufen",
    },
    // What lies at the address (DetectedKind)
    kind: {
      pdf: "PDF",
      docx: "Word (DOCX)",
      rtf: "RTF",
      html: "Webseite (HTML)",
      other: "andere Datei",
    },
    notes: {
      heading: "Zugangsnotizen",
      intro: "Hinweise des Vergleichsdatensatzes zu Land, Schulform und Fach: gesperrte Portale und Umwege.",
      none: "Keine Zugangsnotiz für Land, Schulform und Fach dieses Eintrags.",
    },
  },
  // An entry's file converted into blocks (ConversionPanel.vue, conversionWords.ts). Not
  // "conversion": the guards read "conversion.status" in a template as a key of the group.
  conversions: {
    heading: "Umwandlung in Blöcke",
    intro:
      "Die Umwandlung liest die Datei in Blöcke: Absätze, Überschriften, Tabellen, bei PDFs auch Kopf- und " +
      "Fußzeilen, " +
      "jeden mit einer ID, über die spätere Schritte ihn zitieren. Sie läuft im Hintergrund weiter, auch wenn du " +
      "die Seite verlässt.",
    start: "In Blöcke umwandeln",
    // an event, not a state: the line stays once the job has ended
    started: "Die Umwandlung wurde gestartet.",
    startFailed: "Die Umwandlung wurde nicht gestartet.",
    loadFailed: "Der Stand der Umwandlung wurde nicht geladen.",
    jobLabel: "Umwandlung in Blöcke",
    // waiting with no job this reader may follow (another account's, an editor's start)
    following: "Die Umwandlung wartet oder läuft; diese Seite fragt nach, bis sie fertig ist.",
    done: "Die Umwandlung ist fertig: {pages} {pages|Seite|Seiten} gelesen.",
    failed: "Die Umwandlung ist gescheitert.",
    facts: {
      pages: "Seiten",
      engine: "Werkzeug",
      finishedAt: "Abgeschlossen",
    },
    findingsHeading: "Befunde",
    noFindings: "Die Umwandlung fand nichts Auffälliges im Text.",
    showBlocks: "Blöcke ansehen",
    // the job was cancelled before it ended (a conversion's error_code "cancelled")
    cancelled: "Sie wurde abgebrochen. Starte sie neu, wenn du die Blöcke brauchst.",
    // the same, on the entry's page, where the cancel is the reader's own doing: no failure
    stopped: "Die Umwandlung wurde abgebrochen. Starte sie neu, wenn du die Blöcke brauchst.",
    // the same where no engine the service offers reads the file any more: no start (noRestart follows)
    cancelledNoStart: "Die Umwandlung wurde abgebrochen.",
    noRestart:
      "Neu starten lässt sie sich erst, wenn der Dienst wieder ein Werkzeug anbietet, das diese Datei liest; " +
      "frag dafür die Administration.",
    // its job failed again and again on the service, not on the file (a conversion's "handler_error")
    handlerError:
      "Sie ist mehrmals gescheitert, ohne dass sich die Datei als Ursache zeigte. Versuch es später noch " +
      "einmal; bleibt es dabei, melde es der Administration.",
    pageRange: "{from}–{to}",
    // a sign of the document, quoted in a sentence of the page
    quoted: "„{text}“",
    // what the conversion noticed in the text (backend FindingCode)
    findings: {
      unmapped_symbol:
        "{count} {count|Zeichen|Zeichen} einer Symbolschrift ({codepoint}) auf {pageCount|Seite|Seiten} {pages} " +
        "nicht zugeordnet; in den Blöcken {count|steht es|stehen sie} unverändert, oft als Aufzählungszeichen.",
      encoding_suspect:
        "Die Textebene wirkt beschädigt: {count} {count|verdächtiges Zeichen|verdächtige Zeichen} ({share} des Texts), " +
        "etwa {examples}. Prüfe die Blöcke, bevor du aus ihnen zitierst.",
      // text the conversion left out of the blocks, its signs counted, by why (backend DropReason)
      text_dropped: {
        vertical:
          "{count} {count|Zeichen|Zeichen} Text auf {pageCount|Seite|Seiten} {pages} {count|steht|stehen} " +
          "senkrecht oder gedreht, oft ein Vermerk am Rand; die Blöcke lassen {count|es|sie} aus.",
        off_page:
          "{count} {count|Zeichen|Zeichen} Text auf {pageCount|Seite|Seiten} {pages} {count|steht|stehen} " +
          "außerhalb der sichtbaren Seite; die Blöcke lassen {count|es|sie} aus, denn niemand sieht " +
          "{count|es|sie} beim Lesen.",
        tiny:
          "{count} {count|Zeichen|Zeichen} Text auf {pageCount|Seite|Seiten} {pages} {count|ist|sind} kleiner " +
          "als ein Punkt gesetzt und beim Lesen nicht zu sehen; die Blöcke lassen {count|es|sie} aus.",
        unplaced:
          "{count} {count|Zeichen|Zeichen} Text auf {pageCount|Seite|Seiten} {pages} {count|hat|haben} in der " +
          "Datei keinen gültigen Platz; die Blöcke lassen {count|es|sie} aus.",
        hidden:
          "{count} {count|Zeichen|Zeichen} Text auf {pageCount|Seite|Seiten} {pages} {count|ist|sind} in der " +
          "Datei verborgen und beim Lesen nicht zu sehen; die Blöcke lassen {count|es|sie} aus.",
      },
      // pages read by text recognition (OCR), the least sure page's confidence as a share
      ocr_read:
        "{pageCount|Seite|Seiten} {pages} {pageCount|ist|sind} eingescannt und {pageCount|wurde|wurden} per Texterkennung " +
        "gelesen; Wörter können falsch erkannt sein (Sicherheit auf der unsichersten Seite im Mittel {confidence}). " +
        "Prüfe Zitate von dort am Original.",
      // a DOCX or an HTML page has no pages: the conversion cuts it into pages of about so many signs
      flow_pages:
        "Die Datei hat keine festen Seiten wie ein PDF. Die Umwandlung teilt sie in Abschnitte von rund {signs} " +
        "{signs|Zeichen|Zeichen} und zählt jeden als Seite – in Zitaten und im Seitenkontingent; ein Absatz wird dabei nicht geteilt.",
      // a finding the page has no words for yet, or whose numbers did not come
      other: "Ein Befund, den diese Seite noch nicht beschreibt: {code}.",
    },
    // text a DOCX or an HTML page hides from its reader, left out before the file was cut into pages: on no
    // page (a text_dropped finding without pages, by its reason)
    unpagedDrops: {
      hidden:
        "{count} {count|Zeichen|Zeichen} Text {count|ist|sind} in der Datei als verborgen markiert oder " +
        "unsichtbar gesetzt – etwa ausgeblendet oder nur für Vorleseprogramme versteckt –; die Blöcke lassen " +
        "{count|es|sie} aus.",
      tiny:
        "{count} {count|Zeichen|Zeichen} Text {count|ist|sind} kleiner als ein Punkt gesetzt und beim Lesen " +
        "nicht zu sehen; die Blöcke lassen {count|es|sie} aus.",
    },
  },
  // The blocks of an entry's converted file, a page at a time (ConversionView.vue)
  conversionPage: {
    // a block the anchors of the row chosen in a document's tree name (BlockList.vue)
    cited: "Beleg",
    // the page's heading until the entry names it
    heading: "Blöcke",
    back: "Zurück zum Eintrag",
    intro:
      "Die Blöcke der Datei, Seite für Seite, so wie die Umwandlung sie gelesen hat. Mit der ID eines Blocks " +
      "oder einer Tabellenzelle zitieren spätere Schritte die Stelle.",
    // the browser's title: the entry, and the page shown
    tabTitle: "{title}, Seite {page}",
    loadFailed: "Die Blöcke wurden nicht geladen.",
    pageFailed: "Die Blöcke dieser Seite wurden nicht geladen.",
    hiddenTitle: "Nur für die Redaktion",
    notConvertedTitle: "Noch keine Blöcke",
    failedBody: "Die Umwandlung ist gescheitert. Warum, und wie du sie neu startest, zeigt die Seite des Eintrags.",
    toEntry: "Zur Seite des Eintrags",
    pageHeading: "Seite {page} von {pages}",
    printed: "Gedruckte Seitenzahl: {printed}",
    // what a screen reader hears once a page the reader moved to shows
    announce: "Seite {page} von {pages}: {count} {count|Block|Blöcke}.",
    emptyTitle: "Auf dieser Seite steht kein Text",
    emptyBody: "Die Umwandlung fand hier weder Text noch Tabelle, etwa weil die Seite nur ein Bild trägt.",
    noPageTitle: "Diese Seite gibt es nicht",
    noPageBody: "Die Datei hat {pages} {pages|Seite|Seiten}.",
    firstPage: "Zur ersten Seite",
    pager: {
      // names the landmark, so a screen reader can list it and jump to it by name
      label: "Seiten",
      previous: "Vorige Seite",
      next: "Nächste Seite",
      field: "Seite",
      of: "von {pages}",
      go: "Anzeigen",
      invalid: "Gib eine Seite von 1 bis {pages} an.",
    },
    // what a block is, where it is more than text (backend BlockKind). Read as
    // messages.conversionPage.kind[value]: a value holds an underscore.
    kind: {
      table: "Tabelle",
      page_header: "Kopfzeile",
      page_footer: "Fußzeile",
    },
    bold: "fett",
    italic: "kursiv",
    // a table begun on an earlier page, at the top of a page it runs on to
    continued: "Fortsetzung von Seite {page}",
    tableStart: "Zum Anfang auf Seite {page}",
    table: {
      caption: "Tabelle {table}",
      continuedCaption: "Tabelle {table}, Fortsetzung",
      // a cell of a table that runs on from the page before
      onPage: "auf Seite {page}",
    },
  },
  // A job the page follows (jobWatch.ts), and why one failed (jobMessages.ts).
  jobs: {
    status: {
      queued: "Wartet",
      running: "Läuft",
      done: "Fertig",
      failed: "Fehlgeschlagen",
      cancelled: "Abgebrochen",
    },
    // what a screen reader hears on each change
    announce: "{label}: {status}",
    // how long a job has run or waited, in whole minutes and hours (JobProgress.vue)
    runningFor: "läuft seit {minutes} {minutes|Minute|Minuten}",
    runningJustNow: "läuft seit weniger als einer Minute",
    runningForHours: "läuft seit {hours} {hours|Stunde|Stunden} und {minutes} {minutes|Minute|Minuten}",
    runningForHoursOnly: "läuft seit {hours} {hours|Stunde|Stunden}",
    waitingFor: "wartet seit {minutes} {minutes|Minute|Minuten}",
    waitingJustNow: "wartet seit weniger als einer Minute",
    waitingForHours: "wartet seit {hours} {hours|Stunde|Stunden} und {minutes} {minutes|Minute|Minuten}",
    waitingForHoursOnly: "wartet seit {hours} {hours|Stunde|Stunden}",
    // handed back to the queue after a try: it waits for the next
    waitingAgain: "wartet auf den nächsten Versuch",
    // a cancel from the page: asked first, then followed until the job has ended (JobProgress.vue)
    cancel: {
      button: "Abbrechen",
      name: "Auftrag „{label}“ abbrechen",
      title: "Auftrag abbrechen?",
      message:
        "„{label}“ wird beendet. Was schon fertig ist, bleibt erhalten; du kannst den Auftrag danach neu starten.",
      confirm: "Auftrag abbrechen",
      keep: "Weiterlaufen lassen",
      requested: "Abbruch angefordert – der Auftrag endet in Kürze.",
      ended: "Der Auftrag ist schon beendet.",
      gone: "Den Auftrag gibt es nicht mehr, oder er ist nicht deiner.",
      failed: "Der Abbruch hat nicht geklappt. Versuch es gleich noch einmal.",
    },
    // how far a job has come, as it reports it (JobProgress.vue, PROGRESS)
    progress: {
      checking: "{done} von {total} {total|Adresse|Adressen} angesehen",
      converting: "Die Datei wird in Blöcke umgewandelt; bei einer großen Datei dauert das einige Minuten.",
      // extract.run: the stages X1 to X5 of a document
      extract_profile: "Das Sprachmodell liest Titel, Geltung und Begriffe des Dokuments.",
      // a count of 0 too: the lexicon's patterns may type every heading
      extract_outline: "Die Gliederung wird gebaut. Überschriften, die das Sprachmodell einordnet: {headings}.",
      extract_segments: "Das Dokument wird in {units} {units|Arbeitspaket|Arbeitspakete} geteilt.",
      extract_frame:
        "Das Sprachmodell liest die Rahmenteile: Kompetenzmodelle, Operatoren, Legenden, Regeln und Ziele.",
      // a unit is done once written: those done stay when the job stops
      extract_statements:
        "Das Sprachmodell liest die Aussagen der Arbeitspakete: {done} von {total} {total|Paket|Paketen} fertig.",
      // X5 asks no model; its SHACL check of a long document may take minutes
      check_document:
        "Das Dokument wird geprüft: ob jeder Wortlaut in seinen Blöcken steht, ob die Angaben stimmig sind und ob sie den Regeln des Curriculum-Kerns genügen. Bei einem langen Dokument kann das einige Minuten dauern.",
      // X6: only the work packages with findings, each once a repair
      repair_units:
        "Das Sprachmodell liest die Arbeitspakete mit Befunden noch einmal: {done} von {total} {total|Paket|Paketen} fertig.",
      // the import of a MEM plan: its tree read at the endpoint, then its wordings looked for in the document
      mem_read: "Der Lehrplan wird bei MEM-Schule abgefragt.",
      mem_anchor:
        "Die Wortlaute des Lehrplans werden im Dokument gesucht. Bei einem langen Dokument kann das einige Minuten dauern.",
    },
    trouble: "Der Server antwortet gerade nicht; der Stand wird weiter abgefragt.",
    // why there is nothing left to ask (jobWatch.ts, JobGone); for a fetch and the seed's check alike
    goneReasons: {
      unauthorized: "Deine Anmeldung ist abgelaufen. Melde dich neu an; was der Auftrag erreicht hat, zeigt danach das Register.",
      forbidden: "Diesen Auftrag darf dein Konto nicht verfolgen. Rollen vergibt die Administration.",
      not_found: "Dieser Auftrag ist nicht mehr zu finden. Was er erreicht hat, zeigt das Register unten.",
    },
    failedUnknown: "Der Auftrag ist fehlgeschlagen. Versuch es noch einmal; scheitert er wieder, melde es der Administration.",
    failures: {
      // also a host that does not resolve: an internal name and a misspelt one answer alike
      url_not_allowed:
        "Die Adresse ließ sich nicht auflösen oder führt in ein internes Netz; der Server ruft sie nicht ab. " +
        "Prüfe sie im Browser; stimmt sie, lade die Datei stattdessen hoch.",
      download_refused:
        "Der fremde Server hat die Datei verweigert, etwa weil es sie dort nicht gibt. Prüfe die Adresse im Browser.",
      unsupported_type:
        "Unter der Adresse liegt keine Datei, die Curricarta lesen kann. Oft ist es eine Webseite, " +
        "die erst zum Dokument verlinkt: Nimm dann die Adresse des Dokuments selbst.",
      archive_too_large:
        "Die Datei unter der Adresse ist ein Archiv, das ausgepackt zu groß wird. Prüfe, ob es wirklich ein " +
        "Word-Dokument ist.",
      source_missing: "Der Registereintrag hat keine Adresse, die abgerufen werden könnte. Lege ihn mit der Adresse neu an.",
      file_too_large:
        "Die Datei unter der Adresse ist größer, als ein Upload sein darf. Lade eine kleinere Fassung herunter " +
        "und lade sie hoch, oder teile sie auf.",
      too_many_redirects:
        "Die Adresse leitet immer weiter, ohne bei einer Datei anzukommen. Öffne sie im Browser und nimm die " +
        "Adresse, bei der das Dokument erscheint.",
      bad_answer:
        "Der fremde Server hat so geantwortet, dass sich keine Datei daraus lesen ließ. Lade das Dokument im " +
        "Browser herunter und lade es hoch.",
      download_throttled:
        "Der fremde Server bittet, ihn seltener anzufragen. Versuch es später noch einmal, oder lade das " +
        "Dokument im Browser herunter und lade es hoch.",
      // a conversion into blocks (source.convert)
      conversion_gone: "Diese Umwandlung steht nicht mehr im Register, etwa weil ihre Datei entfernt wurde.",
      unreadable:
        "Die Datei lässt sich nicht lesen; sie ist vielleicht beschädigt. Öffnet sie sich in ihrem Programm, " +
        "speichere sie dort neu und lade sie noch einmal hoch.",
      too_many_pages:
        "Die Datei hat mehr Seiten, als Curricarta umwandelt; bei DOCX und HTML zählt ein Abschnitt " +
        "von rund 3000 Zeichen als Seite. Teile sie auf und lade die Teile einzeln hoch.",
      too_dense:
        "Eine Seite der Datei – bei DOCX und HTML ein einzelner Absatz oder eine Tabellenzeile – trägt weit mehr " +
        "Text, als eine Seite " +
        "fassen kann, oder eine Tabelle gibt weit mehr Zellen an, als eine Seite fasst; die Datei wurde nicht " +
        "umgewandelt. Prüfe, ob sie das Dokument selbst ist, und lade sonst " +
        "eine andere Fassung hoch.",
      needs_ocr:
        "Zu wenige Seiten der PDF-Datei tragen Text; sie ist wohl eingescannt, und diese Umwandlung liest keine " +
        "Scans. Starte sie neu: Bietet der Dienst eine Texterkennung an, liest er die Datei damit (das kostet Seiten " +
        "deines Kontingents). Sonst nimm eine Fassung mit Text.",
      empty:
        "Die Umwandlung fand außer Kopf- und Fußzeilen keinen Text. Prüfe, ob die Datei das Dokument selbst ist " +
        "und nicht nur sein Deckblatt.",
      timed_out:
        "Die Umwandlung hat länger gedauert, als sie darf. Versuch es später noch einmal; eine sehr große Datei " +
        "teile auf.",
      died:
        "Die Umwandlung wurde beendet, wohl weil sie zu viel Speicher brauchte. Teile die Datei auf, oder melde " +
        "es der Administration.",
      crashed:
        "Die Umwandlung ist an dieser Datei gescheitert; ein neuer Versuch ginge ebenso aus. Speichere die Datei " +
        "in ihrem Programm neu und lade sie noch einmal hoch, oder melde es der Administration.",
      not_pdf:
        "Die gespeicherte Datei ist nicht von der Art, die ihr Eintrag angibt, oder das gewählte Werkzeug liest " +
        "diese Art nicht. Lade sie neu hoch.",
      file_gone: "Die Datei fehlt im Speicher des Servers. Melde das bitte der Administration.",
      no_pages:
        "Das Konto, das diese Umwandlung mit Docling gestartet hat, hatte weniger Seiten übrig, als die Datei hat. " +
        "Ohne Docling umgewandelt kostet sie keine Seiten – eine eingescannte Datei, DOCX und HTML liest aber nur Docling; mehr " +
        "Seiten vergibt die Administration.",
      too_many_ocr_pages:
        "Mehr Seiten der PDF-Datei sind eingescannt, als eine Umwandlung per Texterkennung liest. Teile die Datei " +
        "auf und lade die Teile einzeln hoch.",
      handler_error:
        "Der Auftrag ist mehrmals gescheitert, etwa weil ein fremder Server nicht antwortete. " +
        "Versuch es später noch einmal.",
      result_not_storable: "Das Ergebnis ließ sich nicht speichern. Melde das bitte der Administration.",
      lease_lost: "Der Auftrag wurde unterbrochen, weil sein Dienst ausfiel. Versuch es noch einmal.",
      // extract.run (backend app/pipeline/run.py, asking.py, unit_question.py)
      // charged to the document's owner, whoever started it; a new start goes on from the last stage done
      budget_exhausted:
        "Das Token-Budget des Kontos, dem das Dokument gehört, ist aufgebraucht; die Extraktion ist beendet. " +
        "Was schon fertig war, bleibt erhalten: Mit mehr Budget setzt ein neuer Start dort fort, wo sie endete. " +
        "Bitte die Administration um mehr Budget.",
      // the watch after X2 (backend app/pipeline/watch.py): neither the frame nor a part was asked or charged
      run_over_budget:
        "Das restliche Token-Budget des Kontos, dem das Dokument gehört, reicht voraussichtlich nicht für den " +
        "Rest der Extraktion. Sie wurde deshalb beendet, bevor das Sprachmodell weiter gefragt wurde. Was " +
        "schon fertig war, bleibt erhalten: Mit mehr Budget setzt ein neuer Start dort fort, wo sie endete. " +
        "Bitte die Administration um mehr Budget.",
      model_unanswered:
        "Das Sprachmodell hat auch nach mehreren Versuchen keine verwertbare Antwort geliefert. Starte die " +
        "Extraktion später noch einmal; scheitert sie wieder, melde es der Administration.",
      // an answer cut at the output cap (backend app/pipeline/asking.py); the operator raises the limit
      answer_cut:
        "Eine Antwort des Sprachmodells wurde an der Längengrenze für Antworten abgeschnitten; dieser Teil " +
        "bleibt offen. Die Administration kann die Längengrenze für Antworten anheben.",
      model_not_configured: "Für das Sprachmodell ist kein Zugang eingerichtet. Melde das bitte der Administration.",
      // the provider refused a request for good: a 4xx but 408 and 429, or a 429 saying the credit at the
      // provider is spent (backend app/pipeline/side_by_side.py)
      model_refused:
        "Der Anbieter des Sprachmodells hat die Anfrage abgelehnt (Schlüssel, Modellname, Anfrage oder " +
        "aufgebrauchtes Guthaben beim Anbieter). Das kann nur die Administration beheben; ein neuer Start " +
        "hilft nicht.",
      // not even one section beside the title pages and the frame fits the model's context
      prefix_too_long:
        "Ein Abschnitt des Dokuments ist zu lang, als dass das Sprachmodell ihn zusammen mit Titelei und " +
        "Rahmenteilen lesen könnte. Teile das Dokument auf, oder melde es der Administration.",
      document_gone: "Das Dokument gibt es nicht mehr; der Auftrag ist entfallen.",
      // a repair needs the extraction to have come to its check (X5)
      document_not_checked:
        "Die Extraktion des Dokuments ist noch nicht bis zur Prüfung gelaufen. Setze sie erst fort; danach " +
        "lässt es sich reparieren und erneut prüfen.",
      // the editors took away a node a stage still wrote to, while it waited for the tree
      node_gone:
        "Ein Knoten wurde gelöscht, an dem die Stufe noch schreiben wollte. Eine neue Reparatur " +
        "lässt ihn aus; bleibt die Extraktion daran hängen, melde es der Administration.",
      // the catalogue of MEM-Schule's plans: the other graphs were read, the job names the refused ones
      mem_refused:
        "Der MEM-Endpunkt hat eine Antwort gegeben, die sich nicht lesen ließ; Näheres steht in der " +
        "Fehlermeldung des Auftrags. Versuch es später noch einmal; bleibt es dabei, melde es der Administration.",
      // the import of a MEM plan whose plan is gone from the endpoint or the catalogue
      mem_unknown_plan:
        "Der Lehrplan steht nicht mehr bei MEM-Schule oder nicht mehr im Katalog; der Import wurde nicht " +
        "ausgeführt. Bitte die Administration, den Katalog neu einzulesen, und wähle den Plan dann erneut.",
      // the import of a MEM plan whose tree the document's profile does not take
      mem_unwritable:
        "Der Lehrplan ließ sich nicht in das Dokument übernehmen: Ein Wert des Plans passt nicht zu den " +
        "Regeln dieser Installation. Bitte die Administration, den Fehler im Protokoll nachzusehen.",
      // the catalogue or an import: the endpoint answered no attempt
      mem_unavailable:
        "MEM-Schule war bei keinem Versuch erreichbar; es wurde nichts übernommen. Versuch es später noch " +
        "einmal; bleibt es dabei, melde es der Administration.",
      // a document the extraction wrote ends done: this one holds what no extraction wrote
      document_has_tree:
        "Am Dokument stehen schon Knoten oder Spezifikationen, die keine Extraktion angelegt hat; die " +
        "Extraktion schreibt nur in ein Dokument ohne sie. Lege dafür aus der Quelle ein neues Dokument an.",
    },
  },
  dialog: {
    // The confirm dialog's default: it asks before something is removed.
    confirm: "Löschen",
    cancel: "Abbrechen",
  },
  states: {
    loading: "Wird geladen …",
    retry: "Erneut versuchen",
    // A sentence, with its full stop: a failure's reason may follow it.
    errorTitle: "Etwas ist schiefgelaufen.",
    offline: "Der Server ist nicht erreichbar. Prüfe die Verbindung und versuch es noch einmal.",
    tooManyRequests:
      "Zu viele Anfragen in kurzer Zeit. Versuch es in {count} {count|Sekunde|Sekunden} noch einmal.",
  },
  // The page's own words for the refusals the server names by a code
  // (REFUSAL_CODES in refusals.ts), each saying why and what to do next.
  refusals: {
    forbidden: "Dafür fehlt deinem Konto die nötige Rolle. Rollen vergibt die Administration.",
    // the backend's code for every 503, not only the database's
    service_unavailable: "Der Dienst antwortet gerade nicht. Versuch es in ein paar Sekunden noch einmal.",
    validation_failed: "Die Eingabe ist so nicht gültig. Prüfe sie und versuch es noch einmal.",
    file_too_large: "Die Datei ist größer, als ein Upload sein darf. Verkleinere sie oder teile sie auf.",
    // a body cut at its limit before any route read it
    content_too_large: "Die Datei ist größer, als der Server annimmt. Verkleinere sie oder teile sie auf.",
    archive_too_large: "Die Datei ist ein Archiv, das ausgepackt zu groß wird. Ein gewöhnliches Word-Dokument ist das nicht.",
    unsupported_type:
      "Diese Art Datei kann Curricarta nicht lesen. Möglich sind PDF, Word (DOCX), RTF, HTML, " +
      "Markdown, Text (UTF-8) und Turtle.",
    file_missing: "Es kam keine Datei an. Wähle eine Datei aus und versuch es noch einmal.",
    title_invalid: "Der Titel enthält Steuer- oder unsichtbare Zeichen. Tippe ihn neu, statt ihn einzufügen.",
    title_too_long: "Der Titel ist zu lang. Kürze ihn auf höchstens 500 Zeichen.",
    url_invalid:
      "Diese Adresse ruft der Server nicht ab. Eine Webadresse beginnt mit https:// oder http:// " +
      "und enthält keine Zugangsdaten.",
    too_many_uploads: "Du hast gerade viele Dateien hochgeladen. Warte eine Minute und versuch es dann noch einmal.",
    too_many_imports: "Du hast gerade viele Adressen abgerufen. Warte eine Minute und versuch es dann noch einmal.",
    uploads_busy: "Gerade laden viele gleichzeitig hoch. Versuch es in ein paar Sekunden noch einmal.",
    upload_too_slow:
      "Die Datei kam zu langsam an, der Server hat das Hochladen abgebrochen. Versuch es mit einer " +
      "schnelleren Verbindung oder einer kleineren Datei noch einmal.",
    too_many_conversions:
      "Du hast gerade viele Umwandlungen gestartet. Warte eine Minute und versuch es dann noch einmal.",
    no_pages:
      "Dein Konto hat kein Seitenkontingent mehr für die Umwandlung mit Docling. Bitte die Administration um mehr Seiten.",
    // an entry's content: its file and what the conversion read from it
    file_hidden: "Die Datei dieses Eintrags und was aus ihr gelesen wurde, sieht nur die Redaktion.",
    no_file: "Der Eintrag hat noch keine Datei. Sie kommt mit dem Hochladen oder dem Abruf seiner Adresse.",
    not_pdf:
      "Diese Datei wandelt der Dienst nicht in Blöcke um. Er wandelt PDF-Dateien um, DOCX- und HTML-Dateien nur, " +
      "wenn er Docling anbietet.",
    no_conversion: "Die Datei wurde noch nicht in Blöcke umgewandelt. Die Umwandlung startest du auf der Seite des Eintrags.",
    not_converted: "Die Umwandlung ist noch nicht fertig. Wie weit sie ist, zeigt die Seite des Eintrags.",
    no_such_page: "Diese Seite gibt es in der Datei nicht.",
    // a document and its extraction (backend app/api/documents.py), and a model job's admission (limits.py)
    no_document: "Dieses Dokument gibt es nicht, oder dein Konto sieht es nicht.",
    not_owner: "Extraktion und Reparatur startet nur, wer das Dokument angelegt hat.",
    unknown_sector: "Diesen Bildungsbereich kennt die Anwendung nicht.",
    unknown_region: "Eines der gewählten Länder kennt die Anwendung nicht.",
    no_budget: "Dein Konto hat kein Token-Budget mehr für das Sprachmodell. Bitte die Administration um mehr Budget.",
    too_many_jobs: "Dein Konto hat schon viele Aufträge laufen. Versuch es in einer Minute noch einmal.",
    too_many_starts: "Zu viele Starts in kurzer Zeit. Versuch es in einer Minute noch einmal.",
    not_checked:
      "Das Dokument ist noch nicht bis zur Prüfung gekommen. Setze seine Extraktion erst fort – bei einem " +
      "Import aus MEM-Schule: Starte den Import erneut.",
    nothing_to_repair: "Kein Arbeitspaket hat mehr Befunde, die eine Reparatur angeht.",
    // an editor's change to a document's nodes and statements (backend app/api/edit_answers.py and its routes)
    no_node: "Diesen Knoten gibt es nicht mehr, oder dein Konto sieht ihn nicht.",
    no_statement: "Diese Aussage gibt es nicht mehr, oder dein Konto sieht sie nicht.",
    // a specification's title, field, values and contexts (backend app/api/specifications.py)
    no_specification: "Diese Spezifikation gibt es nicht mehr, oder dein Konto sieht sie nicht.",
    // a rule's change (backend app/api/rules.py)
    no_rule: "Diese Regel gibt es nicht mehr, oder dein Konto sieht sie nicht.",
    no_assessment: "Diese Prüfung gibt es nicht mehr, oder dein Konto sieht sie nicht.",
    stale_revision: "Jemand hat das inzwischen geändert. Sieh dir den neuen Stand an und entscheide dann.",
    invalid_field: "Ein Feld lässt sich so nicht setzen. Prüfe die markierte Eingabe.",
    anchor_missing: "Eine Aussage braucht mindestens eine Fundstelle: Blöcke der Quelle oder eine Seite.",
    job_open: "Zu diesem Dokument läuft gerade ein Auftrag. Das geht wieder, sobald er fertig ist.",
    frozen: "Das Dokument ist festgeschrieben. Änderungen gehen nur in einer Entwurfskopie.",
    no_form: "Für den Bildungsbereich dieses Dokuments gibt es kein Formular zum Bearbeiten.",
    not_extracted:
      "Die Extraktion hat noch nicht alle Arbeitspakete gelesen. Erst wenn der Eigentümer sie fortgesetzt hat, " +
      "lässt sich das Dokument bearbeiten – bei einem Import aus MEM-Schule: Starte den Import erneut; " +
      "bearbeiten lässt es sich, sobald er den Baum geschrieben hat.",
    not_editor: "Das darf nur die Redaktion.",
    // a document's work and metadata, frozen and copied (backend app/api/document_meta.py, freeze.py)
    named:
      "Das Dokument hat schon seine IRI. Werk, Herausgeber und Fassung, aus denen sie besteht, bleiben, " +
      "wie sie sind.",
    no_work: "Dieses Werk gibt es nicht.",
    incomplete:
      "Zum Festschreiben fehlt noch etwas: das Werk mit Land und Kurztitel, der Herausgeber oder die Fassung " +
      "(beide mit mindestens einem lateinischen Buchstaben oder einer Ziffer).",
    no_iri_base: "Der Dienst hat keine IRI-Basis (IRI_BASE). Ohne sie lässt sich nichts festschreiben.",
    check_owed:
      "Die Prüfung steht aus: Das Dokument wurde noch nicht geprüft, nicht seit den letzten Änderungen " +
      "oder nicht seit die Prüfung erweitert wurde. " +
      "Prüfe es – oder setze die Extraktion fort, wenn sie nie bis zur Prüfung kam –, dann lässt es sich " +
      "festschreiben.",
    has_violations: "Die Befunde nennen Verstöße. Festschreiben geht nur, wenn du sie ausdrücklich annimmst.",
    iri_taken: "Ein anderes Werk oder Dokument hat diese IRI schon.",
    not_frozen: "Das Dokument ist noch nicht festgeschrieben. Ändere es direkt.",
    not_latest: "Es gibt schon eine spätere festgeschriebene Revision. Kopiere diese.",
    draft_open: "Zu diesem Dokument ist schon ein Entwurf offen.",
    vocabulary_changed:
      "Das Vokabular hat sich seit dem Festschreiben geändert: Eine Zeile des Dokuments passt nicht mehr dazu. " +
      "Bitte die Administration, das Vokabular zu prüfen.",
    not_extractable:
      "Dieses Dokument wird nicht extrahiert: Eine Entwurfskopie und ein Import aus MEM-Schule bringen ihren " +
      "Baum mit. Bearbeite und prüfe es. Brach der Import ab, bevor er den Baum schrieb: Starte den Import erneut.",
    // an import from MEM-Schule
    mem_no_conversion:
      "Zu diesem Eintrag gibt es keine fertige Umwandlung, in die sich der Lehrplan importieren lässt. " +
      "Die Umwandlung startest du auf der Seite des Eintrags.",
    mem_unknown_plan:
      "Diesen Lehrplan nennt der Katalog von MEM-Schule nicht (mehr). Lade die Liste der Pläne neu und wähle " +
      "einen Plan, der dort steht.",
    mem_plan_taken:
      "Dieser Lehrplan wurde in diese Umwandlung schon importiert, oder sein Import läuft gerade. " +
      "Öffne das vorhandene Dokument.",
    // the catalogue's reading, started while one waits or runs: the page follows that one
    catalog_running: "Der Katalog wird schon eingelesen; sein Stand steht hier.",
    // the export of a frozen import from MEM-Schule
    not_mem_import: "Nur ein Import aus MEM-Schule lässt sich als RDF von MEM-Schule exportieren.",
    export_not_frozen: "Exportieren lässt sich nur ein festgeschriebenes Dokument. Schreibe es zuerst fest.",
    export_invalid:
      "Das Dokument erfüllt die Regeln von MEM-Schule nicht; die Liste nennt die betroffenen Stellen. Zeilen " +
      "bearbeitest du in einer Entwurfskopie. Fehlt dem Dokument selbst etwas, etwa das Land des Plans, " +
      "lässt sich das in der App nicht nachtragen; melde es der Administration.",
    // when to try again the export's section says, in the seconds the server names (useExportDownload.ts)
    export_unavailable:
      "Der Export ist nicht rechtzeitig fertig geworden; bleibt es dabei, melde es der Administration.",
    // the Kern export of a document frozen before its specifications had IRIs (DocumentKernExport.vue)
    export_unnamed:
      "Das Dokument wurde festgeschrieben, bevor seine Spezifikationen IRIs bekamen. Melde es der " +
      "Administration: Sie vergibt die IRIs einmal mit „python -m app.db.name_frozen“, danach lässt es sich " +
      "exportieren.",
    too_many_exports: "Du hast in der letzten Minute viele Exporte angefordert.",
    // the editors' review of the lexicon (LexiconReviewView.vue)
    no_cue: "Diesen Hinweis der Recherche gibt es nicht mehr, und entschieden war er noch nicht. Lade die Liste neu.",
    no_term: "Kein Dokument nennt diesen Begriff mehr, und entschieden war er noch nicht. Lade die Liste neu.",
    not_a_node_type: "Das Ziel ist kein Knotentyp im Profil dieses Bereichs. Wähle einen aus der Liste.",
    too_short:
      "Ein Wort unter vier Zeichen gibt keinen Hinweis: Der Lexikonauszug fände es mitten in anderen Wörtern.",
  },
  // MEM-Schule: its catalogue, the import of its plans and their export (plan M2-8)
  mem: {
    // the catalogue on the import's section (MemCatalog.vue)
    catalog: {
      never: "Der Katalog von MEM-Schule wurde noch nicht eingelesen. Bitte die Administration, ihn einzulesen.",
      neverAdmin: "Der Katalog von MEM-Schule wurde noch nicht eingelesen.",
      readAt: "Katalog zuletzt eingelesen:",
      old: "Der Katalog ist älter als 30 Tage; neuere Pläne von MEM-Schule fehlen vielleicht.",
      start: "Katalog einlesen",
      restart: "Katalog neu einlesen",
      confirmTitle: "Katalog von MEM-Schule einlesen?",
      confirmMessage:
        "Der Server fragt jetzt alle Pläne bei MEM-Schule ab. Das Einlesen läuft im Hintergrund weiter, auch " +
        "wenn du die Seite verlässt.",
      confirm: "Katalog einlesen",
      jobLabel: "Katalog von MEM-Schule",
      startFailed: "Das Einlesen des Katalogs ließ sich nicht starten.",
    },
    // the import of a plan on an entry's page (MemImportPanel.vue)
    import: {
      heading: "Import aus MEM-Schule",
      intro:
        "Übernimmt einen Lehrplan, den MEM-Schule schon als Datensatz führt, in ein neues Dokument dieser " +
        "Umwandlung. Die Wortlaute werden im Dokument gesucht und verankert; danach wird das Dokument geprüft.",
      needsConversion: "Ein Import braucht eine fertige Umwandlung der Datei.",
      toConversion: "Zur Umwandlung",
      loading: "Der Katalog von MEM-Schule wird geladen.",
      loadFailed: "Der Katalog von MEM-Schule ließ sich nicht laden.",
      region: "Land",
      regionAny: "alle",
      regionKmk: "Bund (KMK-Bildungsstandards)",
      title: "Titel enthält",
      search: "Suchen",
      searching: "Wird gesucht …",
      results: "Lehrpläne im Katalog",
      readAt: "Stand",
      shown: "{shown} von {total} {total|Plan|Plänen}",
      more: "Weitere laden",
      moreFailed: "Weitere Pläne ließen sich nicht laden.",
      noneFound: "Kein Plan im Katalog passt zur Suche.",
      chooseMissing: "Wähle einen Lehrplan aus der Liste.",
      attribution: "Namensnennung",
      attributionNone: "nicht angegeben",
      licence: "Lizenz der Daten",
      licenceNone: "nicht genannt; die Datenlizenz von MEM-Schule ist noch ungeklärt",
      rights: "Rechte der Wortlaute",
      rightsNote: "wie am Registereintrag angegeben",
      submit: "Importieren",
      failed: "Der Import ließ sich nicht starten.",
      toDocument: "Zum vorhandenen Dokument",
    },
    // the import on the document's page (DocumentExtraction.vue)
    job: {
      heading: "Import",
      restart: "Import erneut starten",
      restartFailed: "Der Import ließ sich nicht erneut starten.",
      imported: "Der Import hat den Baum geschrieben; prüfen und bearbeiten lässt er sich im Baum.",
      notEditor: "Einen Import starten die Redaktion und die Administration erneut.",
      following: "Der Stand wird weiter abgefragt, bis der Import endet.",
      none: "Noch kein Import.",
    },
    // where an imported document came from (DocumentMemOrigin.vue)
    origin: {
      heading: "Herkunft aus MEM-Schule",
      plan: "Plan",
      attribution: "Namensnennung",
      attributionNone: "nicht angegeben",
      licence: "Lizenz der Daten",
      licenceNone: "nicht genannt; die Datenlizenz von MEM-Schule ist noch ungeklärt",
      rights: "Rechte der Wortlaute",
      rightsNote: "wie beim Eintrag der Quelle angegeben",
    },
    // the export of a frozen import on the document's page (DocumentExport.vue)
    export: {
      heading: "Export für MEM-Schule",
      contains:
        "Die Datei beschreibt das Dokument als RDF nach der Lehrplan-Ontologie von MEM-Schule (Turtle). Sie nennt " +
        "den Plan als Quelle, die Namensnennung und den Rechtestatus der Wortlaute; eine Lizenz nur, wo eine " +
        "eingetragen ist. Vor der Ausgabe wird sie gegen die Regeln von MEM-Schule geprüft.",
      button: "Als RDF für MEM-Schule exportieren",
      working: "Der Export wird geprüft und erstellt; das kann bis zu einer Minute dauern.",
      saved: "Die Datei {name} wurde dem Browser zum Speichern übergeben.",
      failed: "Der Export ließ sich nicht erstellen.",
      wait: "Versuch es in {count} {count|Sekunde|Sekunden} erneut.",
      again: "Versuch es gleich noch einmal.",
      saveFailed: "Die Datei wurde erstellt, ließ sich aber nicht an den Browser übergeben. Versuch es noch einmal.",
      violations: {
        heading: "Verstöße gegen die Regeln von MEM-Schule",
        shown: "{shown} von {total} {total|Verstoß|Verstößen}",
        table: "Verstöße des Exports",
        columns: { place: "Stelle", shape: "Regel", path: "Eigenschaft", message: "Meldung der Prüfung" },
        toRow: "Zeile im Baum öffnen",
        document: "das Dokument",
      },
      // the MEM shapes by what they check (ontology/mem/shapes); one not named here is shown by its name
      shapes: {
        BereichShape: "Bereich (Teil eines Plans)",
        LPBundeslandShape: "Lehrplan mit Bundesland",
        VerweisShape: "Verweis mit Ziel",
        TextualEntityShape: "Textteil",
        DocumentClass: "Dokument mit bekannter Klasse",
      },
    },
  },
  // The editors' review of the lexicon (LexiconReviewView.vue)
  lexicon: {
    page: {
      heading: "Lexikon prüfen",
      intro:
        "Hier entscheidet die Redaktion über die Hinweise der Länderrecherche und über Begriffe, für die die " +
        "Extraktion im Profil keinen Typ fand. Im Lexikon wirken die Entscheidungen erst, wenn die " +
        "Administration sie exportiert und die Länderdateien neu erzeugt.",
      // names the links to the page's two sections
      sections: "Abschnitte dieser Seite",
      // a decision not saved asked about before it goes (LexiconReviewView.vue, leaveGuard.ts)
      leave: {
        // not "Verwerfen": that is what a decision on a research cue may say
        title: "Seite verlassen?",
        message: "Eine Entscheidung ist noch nicht gespeichert. Gehst du weiter, geht sie verloren.",
        confirm: "Ohne Speichern gehen",
        cancel: "Weiter entscheiden",
      },
    },
    // The sample of the research's cues (LexiconSample.vue)
    sample: {
      heading: "Stichprobe der Länderrecherche",
      intro:
        "Ein Zehntel der Hinweise aus der Länderrecherche, je Bildungsbereich und Land, aufgerundet – bei " +
        "jedem Laden dieselben. Bestätige einen Hinweis mit der Fundstelle, an der du ihn geprüft hast, oder " +
        "verwirf ihn.",
      loading: "Die Stichprobe wird geladen …",
      loadFailed: "Die Stichprobe wurde nicht geladen.",
      noneTitle: "Keine Hinweise der Recherche",
      noneBody: "Das Lexikon enthält keine Hinweise aus der Länderrecherche. Es gibt nichts zu prüfen.",
      strata: "Schichten der Stichprobe",
      columns: {
        sector: "Bereich",
        regions: "Länder",
        cues: "Hinweise",
        sampled: "In der Stichprobe",
        decided: "Entschieden",
      },
      // which cues to show, by the strata (LexiconCueFilter.vue)
      filter: {
        sector: "Bildungsbereich",
        anySector: "alle Bereiche",
        region: "Land",
        anyRegion: "alle Länder",
        none: "Kein Hinweis passt zu dieser Auswahl. Wähle einen anderen Bereich oder ein anderes Land.",
      },
      more: "Weitere zeigen",
      shownCount: "{shown} von {total} angezeigt",
      // said once a decision is saved; the second sentence where its cue is shown outside the choice
      saved: "Die Entscheidung ist gespeichert.",
      keptOutside: "Der Hinweis passt nicht zur Auswahl und bleibt sichtbar, bis du die Auswahl änderst.",
      retiredHeading: "Entscheidungen zu ausgemusterten Hinweisen",
      retiredIntro:
        "Eine Ladung der Vokabulare hat diese Hinweise ausgemustert. Was die Redaktion über sie entschied, bleibt " +
        "und lässt sich ändern.",
    },
    // The terms X1 found no type for (LexiconTerms.vue)
    terms: {
      heading: "Neue Begriffe aus der Extraktion",
      intro:
        "Begriffe, für die die Extraktion im Profil keinen Typ fand – je Bereich, Länder und Wort über alle " +
        "Dokumente zusammen. Entscheide, ob einer ein neuer Hinweis fürs Lexikon wird, eine Besonderheit " +
        "seines Dokuments ist oder falsch erkannt wurde.",
      loading: "Die neuen Begriffe werden geladen …",
      loadFailed: "Die neuen Begriffe wurden nicht geladen.",
      noneTitle: "Keine neuen Begriffe",
      noneBody: "Die Extraktion hat in keinem Dokument einen Begriff ohne Typ gefunden.",
      goneHeading: "Entscheidungen zu Begriffen, die kein Dokument mehr nennt",
      goneIntro:
        "Die Dokumente, die diese Begriffe nannten, sind gelöscht oder nennen sie nicht mehr. Was die Redaktion " +
        "über sie entschied, bleibt und lässt sich ändern.",
    },
    // One term X1 found no type for, or a gone one's decision (LexiconTermItem.vue)
    term: {
      documents: "in {count} {count|Dokument|Dokumenten}",
      gone: "von keinem Dokument mehr genannt",
      functions: "Vorgeschlagene Funktionen",
      places: "Fundstellen",
      placeFunction: "vorgeschlagen: {function}",
      more: "und {count} {count|weiteres Dokument|weitere Dokumente}",
      held: "Schon im Lexikon",
      own: "eigenes Lexikon",
      research: "Länderrecherche",
      cue: "Neuer Hinweis auf {target} als {role}.",
      document: "Besonderheit des Dokuments.",
      error: "Fehler der Erkennung.",
      applied: "Die Vokabulare tragen ihn.",
      skipped: {
        word: "Der Import übergeht ihn: Das eigene Lexikon führt das Wort schon.",
        pattern: "Der Import übergeht ihn: Ein Muster des eigenen Lexikons trifft das Wort für dieses Ziel.",
      },
    },
    // What both lists offer to show (LexiconSample.vue, LexiconTerms.vue)
    list: {
      openOnly: "Nur offene zeigen",
      openCount: "{open} von {total} offen",
      allDecided: "Jeder Eintrag der Liste ist entschieden.",
    },
    // One cue of the sample, or a retired one's decision (LexiconCueItem.vue)
    cue: {
      pattern: "Muster",
      everywhere: "bundesweit",
      inSample: "in der Stichprobe",
      outsideSample: "entschieden, außerhalb der Stichprobe",
      retired: "ausgemustert",
      role: "Rolle",
      kind: "Art",
      targets: "Ziele",
      strength: "Stärke",
      noStrength: "nicht angegeben",
      verified: "geprüft",
      unverified: "ungeprüft",
      notes: "Aus der Recherche",
      hints: "Erkennungsmerkmale",
      examples: "Beispiele",
      sources: "Quellen",
      confirmed: "Bestätigt mit Stärke {strength}, Fundstelle: {evidence}.",
      rejected: "Verworfen.",
      appliedConfirmed: "Die Vokabulare führen ihn als geprüft, mit dieser Stärke.",
      appliedRejected: "Die Vokabulare tragen ihn nicht mehr.",
      retiredSince: "Der Hinweis ist inzwischen ausgemustert.",
    },
    // What an entry of either list says of its decision (LexiconCueItem.vue, LexiconTermItem.vue)
    item: {
      decide: "Entscheiden",
      decideAgain: "Neu entscheiden",
      undecided: "Noch nicht entschieden.",
      by: "Entschieden von {name} am {date}.",
      note: "Anmerkung: {note}",
      waiting: "Wartet auf Export und Import.",
    },
    // What the two forms of a decision share (CueDecisionForm.vue, TermDecisionForm.vue)
    form: {
      note: "Anmerkung",
      save: "Entscheidung speichern",
      cancel: "Abbrechen",
      failed: "Die Entscheidung wurde nicht gespeichert.",
      reload: "Liste neu laden",
      // a field's problem, said where the keyboard stayed in another field
      fieldProblem: "{field}: {problem}",
    },
    // A decision on a research cue of the sample (CueDecisionForm.vue)
    cueForm: {
      legend: "Entscheidung",
      confirmed: "Bestätigen",
      rejected: "Verwerfen",
      strength: "Stärke",
      strengthChoose: "Stärke wählen",
      strengthHint: "Wie verlässlich der Hinweis trifft, von 0,50 bis 0,90.",
      evidence: "Fundstelle",
      evidenceHint: "Wo du den Hinweis geprüft hast, etwa „Kernlehrplan Physik NRW, S. 14“.",
      chooseDecision: "Wähle, ob du den Hinweis bestätigst oder verwirfst.",
      chooseStrength: "Wähle eine Stärke.",
      evidenceMissing: "Nenne die Fundstelle: Ohne sie bestätigt die Redaktion keinen Hinweis.",
    },
    // A decision on a term X1 found no type for (TermDecisionForm.vue)
    termForm: {
      legend: "Entscheidung",
      cue: "Neuer Hinweis",
      document: "Besonderheit des Dokuments",
      error: "Fehler der Erkennung",
      target: "Knotentyp",
      targetChoose: "Knotentyp wählen",
      suggested: "Passt zur vorgeschlagenen Funktion",
      others: "Weitere Knotentypen",
      targetsLoading: "Die Knotentypen werden geladen …",
      targetsFailed: "Die Knotentypen wurden nicht geladen.",
      targetsMissing: "Für einen neuen Hinweis fehlen die Knotentypen. Lade sie erst, dann wähle einen.",
      targetsPending: "Die Knotentypen werden noch geladen. Wähle einen, sobald sie da sind.",
      role: "Rolle",
      roleChoose: "Rolle wählen",
      // by the notations of cv:CueRoles a new cue may take, in the vocabulary's words
      roles: {
        pref: "Präferenzbezeichnung",
        alt: "echtes Synonym",
        cue: "Hinweis (kein Synonym)",
      },
      roleHint:
        "Präferenzbezeichnung: der übliche Name des Knotentyps. Echtes Synonym: ein anderer Name dafür. " +
        "Hinweis: ein Wort, das auf den Knotentyp deutet, ohne ihn zu benennen.",
      // why the import would leave the new cue out (lexiconWords.skipReason)
      skipped: {
        word:
          "Das eigene Lexikon führt das Wort schon: Der Import übernimmt keinen neuen Hinweis dazu. Passt eher " +
          "„Fehler der Erkennung“?",
        pattern:
          "Ein Muster des eigenen Lexikons trifft das Wort für diesen Knotentyp: Der Import übernimmt den neuen " +
          "Hinweis nicht. Passt eher „Fehler der Erkennung“?",
      },
      chooseDecision: "Wähle, was der Begriff ist.",
      chooseTarget: "Wähle den Knotentyp, auf den der Hinweis zeigt.",
      chooseRole: "Wähle die Rolle des Hinweises.",
    },
  },
  // Documents of a conversion and their extraction (ExtractionStart.vue, DocumentView.vue, SourceDocuments.vue)
  documents: {
    // by the notations of cv:EducationSectors (tests/documentWords.test.ts)
    sectors: {
      elementary: "Elementarbildung",
      school: "Schulbildung",
      vocational: "Berufsbildung",
      higher: "Hochschulbildung",
      adult: "Erwachsenen- und Weiterbildung",
    },
    stages: {
      X1: "Profil und Gliederung",
      X2: "Arbeitspakete",
      X3: "Rahmenteile",
      X4: "Aussagen",
      X5: "Prüfung",
      X6: "Reparatur",
      IM: "Import",
    },
    runStates: {
      done: "fertig",
      failed: "gescheitert",
      budget_exhausted: "Budget aufgebraucht",
      running: "läuft",
      abandoned: "abgebrochen",
    },
    // why a run failed, where it names a type of failure rather than a code (DocumentRuns.vue); the
    // codes are a job's (jobs.failures), anything else the server's words, quoted
    runFailures: {
      LeaseLost: "Der Lauf ging nicht weiter: Der Auftrag wurde abgebrochen oder vom Server neu vergeben.",
      // an attempt of an import the MEM endpoint did not answer; another follows
      MemUnavailable: "MEM-Schule war nicht erreichbar; ein weiterer Versuch folgt.",
      mem_unavailable: "MEM-Schule war bei keinem Versuch erreichbar.",
    },
    // A document's work packages (DocumentUnits.vue, backend app/pipeline/units.py)
    units: {
      heading: "Arbeitspakete",
      table: "Arbeitspakete des Dokuments",
      loading: "Die Arbeitspakete werden geladen.",
      loadFailed: "Die Arbeitspakete ließen sich nicht laden.",
      noneTitle: "Noch keine Arbeitspakete",
      noneBody: "Sie stehen fest, sobald die Extraktion das Dokument geteilt hat.",
      columns: { key: "Paket", path: "Abschnitt", pages: "Seiten", state: "Stand" },
      // E0: what stands before the first heading; a document without headings is one package
      titlePages: "Titelei",
      wholeDocument: "Ganzes Dokument",
      page: "S. {first}",
      pages: "S. {first}–{last}",
      states: {
        done: "fertig, {statements} {statements|Aussage|Aussagen}",
        open: "offen",
        frame: "Rahmenteil, wird typisiert gelesen",
        none: "wird nicht gelesen",
      },
      // the packages whose statements the extraction reads
      summary: "{done} von {total} {total|Paket|Paketen} mit Aussagen fertig.",
    },
    // What the stages found on a document (DocumentFindings.vue, backend app/api/document_findings.py)
    findings: {
      heading: "Befunde",
      table: "Befunde des Dokuments",
      loading: "Die Befunde werden geladen.",
      loadFailed: "Die Befunde ließen sich nicht laden.",
      noneTitle: "Keine Befunde",
      noneBody: "Die Stufen der Extraktion haben an diesem Dokument bisher nichts gefunden.",
      columns: { severity: "Schwere", finding: "Befund", focus: "Betrifft" },
      // by Severity (backend app/domain/l1.py; tests/documentWords.test.ts)
      severities: { violation: "Verstoß", warning: "Warnung", info: "Hinweis" },
      counts: {
        violation: "{count} {count|Verstoß|Verstöße}",
        warning: "{count} {count|Warnung|Warnungen}",
        info: "{count} {count|Hinweis|Hinweise}",
      },
      truncated: "Gezeigt werden die ersten {shown} von {total} {total|Befund|Befunden}.",
      // the kind of the row a finding is about; another kind is shown as the server names it
      kinds: {
        document: "Dokument",
        node: "Knoten",
        statement: "Aussage",
        frame_part: "Rahmenteil",
        specification: "Spezifikation",
        anchor: "Anker",
        variant: "Variante",
        assessment: "Prüfung", // plan M3a J; a level at one named with it, as at any holder
        // the second layer's values, each named with the row that holds it (valueAt)
        level_assignment: "Niveauzuordnung",
        time_span: "Zeitraum",
        workload: "Umfang",
      },
      // what a finding is about: its kind, its wording or title, the work package it names
      about: "{kind} „{label}“",
      inUnit: "{what}, Paket {unit}",
      // a statement a repair of its package dropped, its findings of an earlier stage staying (findingWords.ts)
      statementGone: "Entfernte Aussage",
      // a value and its holder - a node or a statement, said as `about` says a row
      valueAt: "{value} bei {holder}",
      // a value replaced or taken away since X5 found something on it: its finding stays until X5 checks again
      valueGone: "Entfernter Wert",
      // by the rule's name without its stage: the reading of an answer names its rules alike at X1,
      // X3, X4 and X6 (tests/findingWords.test.ts); SHACL's messages as the server gives them
      rules: {
        // X5's checks
        wording_not_found: "Der Wortlaut steht nicht in den Blöcken, auf die er verweist.",
        import_not_found:
          "Der importierte Wortlaut wurde im Dokument nicht gefunden; die Seite ist nur geschätzt. Bitte die Stelle im Dokument zuordnen.",
        unit_without_statements: "Das Arbeitspaket wurde ganz gelesen, enthält aber keine Aussage.",
        shacl_timeout: "Die Regelprüfung (SHACL) dauerte zu lange; das Ergebnis bleibt gesperrt.",
        anchors_unchecked:
          "Die Prüfung der Fundstellen brauchte zu lange; ein Teil ist noch ungeprüft. Starte die Prüfung erneut.",
        rule_bounds: "Die Grenzen einer Regel widersprechen sich.",
        retired_value: "Ein Wert, den die Vokabulare nicht mehr führen.",
        heading_as_statement: "Eine Aussage, die nur eine Überschrift des Dokuments wiederholt.",
        label_as_statement: "Eine Aussage unklarer Art, die nur eine Beschriftung oder ein Wert ist.",
        lead_in_as_statement: "Eine Aussage, die nur einen Einleitungssatz ihres Abschnitts wiederholt.",
        // what the reading of the model's answer found
        too_many_statements: "Die Antwort enthielt mehr Aussagen, als gelesen werden; die übrigen fehlen.",
        statement_without_block: "Eine Aussage ohne gültige Blockkennung; sie fehlt.",
        statement_without_wording: "Eine Aussage ohne Wortlaut; sie fehlt.",
        statement_too_long: "Eine Aussage über der Längengrenze; sie fehlt.",
        unknown_block: "Eine Blockkennung, die die Umwandlung nicht hat.",
        block_outside_unit: "Ein Block außerhalb des gefragten Arbeitspakets.",
        unknown_value: "Ein Wert, den die Auswahlliste nicht hat.",
        unknown_key: "Eine Kennung, die die Frage nicht genannt hat.",
        subkind_mismatch: "Eine Unterart, die nicht zur Aussageart gehört.",
        value_cut: "Ein Wert, auf die Höchstlänge gekürzt.",
        value_from_surroundings: "Ein Wert aus der Umgebung, nicht aus dem Wortlaut der Aussage.",
        target_not_content: "Ein Verweis auf eine Aussage, die keine Inhaltsaussage ist.",
        part_without_block: "Ein Rahmenteil ohne gültige Blockkennung; es fehlt.",
        statement_outside_frame: "Eine Aussage außerhalb der Rahmenteile; sie wird mit den Arbeitspaketen gelesen.",
        statement_without_node: "Eine Aussage der Titelei, die kein Knoten aufnimmt.",
        target_elsewhere: "Ein Verweis auf Inhalt an einem anderen Knoten oder an keinem.",
        // a stage's own
        unanswered: "Das Sprachmodell gab keine Antwort in der verlangten Form.",
        // X4's (a unit not yet read) and X6's (a package read before): the part stays as it is, and is
        // asked again - also offered for repair - only once the operator has raised the limit
        answer_cut:
          "Die Antwort des Sprachmodells wurde an der Längengrenze für Antworten abgeschnitten und nicht " +
          "übernommen; dieser Teil bleibt, wie er ist. Bis die Administration die Längengrenze für Antworten " +
          "anhebt, wird er weder neu gelesen noch zur Reparatur angeboten.",
        empty_answer: "Die Antwort enthielt keine neue lesbare Aussage, obwohl das Paket welche hat; es bleibt, wie es war.",
        pattern_timeout: "Ein Suchmuster des Lexikons brauchte zu lange und wurde übergangen.",
      },
      // the owner's repair (FindingsRepair.vue, backend POST /documents/{id}/repair)
      repair: {
        offer:
          "{count} {count|Arbeitspaket hat|Arbeitspakete haben} Befunde, die eine Reparatur angeht: Das " +
          "Sprachmodell liest {count|es|sie} noch einmal, danach wird das Dokument erneut geprüft. " +
          "Was die Redaktion geändert hat, bleibt.",
        start: "Reparieren",
        started: "Die Reparatur ist gestartet; ihr Stand steht unter „Extraktion“.",
        // the start gave back the document's extraction, waiting or running
        extractionRunning: "Es läuft schon eine Extraktion des Dokuments; ihr Stand steht unter „Extraktion“.",
        failed: "Die Reparatur wurde nicht gestartet.",
      },
    },
    untitled: "Dokument ohne Titel",
    start: {
      heading: "Extraktion",
      intro:
        "Aus der fertigen Umwandlung wird ein Dokument; das Sprachmodell liest sein Profil, seine Gliederung, " +
        "seine Rahmenteile und die Aussagen jedes Arbeitspakets; danach prüft die Anwendung das Ergebnis, " +
        "ohne Sprachmodell. Fertige Pakete bleiben, auch wenn die " +
        "Extraktion abbricht; ein neuer Start setzt dort fort. " +
        "Für eine Datei läuft bei dir höchstens eine Extraktion zugleich – läuft schon eine, führt der Knopf zu ihr. " +
        "Du kannst sie jederzeit abbrechen.",
      sector: "Bildungsbereich",
      sectorChoose: "Bereich wählen",
      sectorMissing: "Wähle den Bildungsbereich des Dokuments.",
      regions: "Länder",
      regionsHint: "Wofür das Dokument gilt; „Bund“, wenn es für alle Länder gilt.",
      submit: "Extraktion starten",
      failed: "Die Extraktion wurde nicht gestartet.",
    },
    page: {
      loadFailed: "Das Dokument wurde nicht geladen.",
      notFoundTitle: "Dieses Dokument gibt es nicht",
      notFoundBody: "Oder dein Konto sieht es nicht. Deine Dokumente findest du auf den Seiten ihrer Registereinträge.",
      // under the heading: the way back, the first action, the page's sections (DocumentView.vue)
      back: "Zurück zum Eintrag",
      backToRegister: "Zurück zum Register",
      sections: "Abschnitte dieser Seite",
      // leaving the page with drafts in several of its editor sections (DocumentEditors.vue)
      leaveSeveral: "Deine Änderungen auf dieser Seite sind nicht gespeichert. Gehst du weiter, gehen sie verloren.",
      facts: {
        heading: "Angaben",
        sector: "Bildungsbereich",
        regions: "Länder",
        source: "Registereintrag",
        created: "Angelegt",
      },
      sourceLink: "Zum Registereintrag",
      // in its place where the account does not see the entry (DocumentSource.vue says why)
      sourceHidden: "Für dein Konto nicht sichtbar",
      treeLink: "Baum öffnen",
      noRegions: "keine angegeben",
      extraction: "Extraktion",
      jobLabel: "Extraktion",
      // the document's job a repair started (documentJobs.ts)
      repairLabel: "Reparatur",
      none: "Noch keine Extraktion.",
      lastStatus: "Letzte Extraktion: {status}",
      lastRepairStatus: "Letzte Reparatur: {status}",
      checkLabel: "Prüfung",
      lastCheckStatus: "Letzte Prüfung: {status}",
      // the document's job an import of a MEM plan started (documentJobs.ts)
      importLabel: "Import aus MEM-Schule",
      lastImportStatus: "Letzter Import: {status}",
      importStarted: "Der Import ist gestartet; sein Stand steht hier.",
      // its job is another's to follow, or gone: the document is asked after (DocumentExtraction.vue)
      following: "Der Stand wird weiter abgefragt, bis die Extraktion endet.",
      started: "Die Extraktion ist gestartet; ihr Stand steht hier.",
      // a start gave back the document's repair, waiting or running (one job of a document at a time)
      repairRunning: "Es läuft schon eine Reparatur des Dokuments; ihr Stand steht hier.",
      // or its check, waiting or running (documentJobs.startedWords)
      checkRunning: "Die Prüfung läuft; ihr Stand steht hier.",
      // the start form led here: for this file one ran already, and what the form chose was not taken
      ledToRunning:
        "Für diese Datei lief schon eine Extraktion – hier ist sie. Bereich und Länder aus dem Formular " +
        "wurden nicht übernommen; ist sie beendet, kannst du ein weiteres Dokument anlegen.",
      // a frozen document and a draft copy are not extracted (DocumentExtraction.vue)
      frozenNoExtraction: "Das Dokument ist festgeschrieben: Es wird nichts mehr extrahiert.",
      copyNoExtraction: "Eine Entwurfskopie wird nicht extrahiert; prüfen lässt sie sich im Baum.",
      resume: "Extraktion fortsetzen",
      resumeFailed: "Die Extraktion wurde nicht gestartet.",
      notOwn: "Die Extraktion startet nur, wer das Dokument angelegt hat.",
      // the document frozen (documentRevision.ts, DocumentFreeze.vue)
      freeze: {
        // the section and its questions (DocumentFreeze.vue, FreezeDialog.vue)
        heading: "Festschreiben",
        intro:
          "Festgeschrieben bekommen Knoten und Aussagen ihre IRIs, und das Dokument ändert sich nicht mehr. " +
          "Vorher brauchen Werk, Herausgeber und Fassung einen Wert, und die Prüfung muss den letzten Stand " +
          "kennen.",
        button: "Festschreiben",
        title: "Dokument festschreiben?",
        message: "„{title}“, Revision {revision}, wird festgeschrieben. Das lässt sich nicht zurücknehmen.",
        follows: {
          iris: "Knoten und Aussagen bekommen ihre IRIs.",
          fixed: "Baum, Angaben und Werk lassen sich danach nicht mehr ändern.",
          noJobs: "Es wird nichts mehr extrahiert, geprüft oder repariert.",
          copy: "Weiter geht es in einer Entwurfskopie („Als Entwurf kopieren“).",
        },
        violationsTitle: "Trotz Verstößen festschreiben?",
        violationsMessage:
          "Die Befunde nennen {count} {count|Verstoß|Verstöße}. Festschreiben nimmt {count|ihn|sie} an; " +
          "{count|er bleibt|sie bleiben} am Dokument stehen.",
        violationsConfirm: "Trotzdem festschreiben",
        incomplete: "Zum Festschreiben fehlt noch: {missing}.",
        // what the IRI is made of, each with its state, before the button (DocumentFreeze.vue)
        checks: "Was die IRI braucht",
        part: {
          work: "Werk",
          region: "Land des Werks",
          short_title: "Kurztitel des Werks",
          issuer: "Herausgeber",
          edition: "Fassung",
        },
        check: {
          set: "{what}: gesetzt",
          missing: "{what}: fehlt",
        },
        toTree: "Zum Baum: dort „Erneut prüfen“",
        failed: "Das Dokument wurde nicht festgeschrieben.",
        // what its IRI still lacks, item by item (backend details.missing)
        missing: {
          work: "das Werk",
          region: "das Land des Werks",
          short_title: "der Kurztitel des Werks",
          issuer: "der Herausgeber",
          edition: "die Fassung",
        },
      },
      // what the document's specifications are and where they apply (plan M3a H1; DocumentScope.vue,
      // SpecificationForm.vue, scopeWords.ts)
      scope: {
        heading: "Geltung",
        intro:
          "Wofür das Dokument steht – Lehrplan, Kompetenzrahmen, Qualifikation oder Prüfung – und wo es gilt: " +
          "Bildungsbereich, Formalität, Einrichtung, Zielgruppe, Zeit und Niveau.",
        loading: "Die Spezifikationen werden geladen …",
        loadFailed: "Die Spezifikationen wurden nicht geladen.",
        noneTitle: "Noch keine Spezifikation",
        noneBody: "Die Extraktion legt sie an, sobald sie das Dokumentprofil gelesen hat.",
        closed: {
          frozen: "Das Dokument ist festgeschrieben: Die Geltung ist nur zu lesen.",
          job_open: "Zu diesem Dokument läuft gerade ein Auftrag: Die Geltung ist bis zu seinem Ende nur zu lesen.",
          not_extracted: "Die Extraktion hat noch nicht jedes Arbeitspaket gelesen: Die Geltung ist bis dahin nur zu lesen.",
        },
        readOnly: "Die Geltung ändern die Eigentümerin oder der Eigentümer des Dokuments und die Redaktion.",
        kinds: {
          curriculum: "Lehrplan",
          competencyFramework: "Kompetenzrahmen",
          qualificationSpecification: "Qualifikation",
          assessmentSpecification: "Prüfung",
        },
        kind: "Art",
        field: "Fach",
        variants: "Varianten",
        values: "Niveau, Zeit und Umfang",
        contexts: "Geltungskontexte",
        none: "nicht angegeben",
        noValues: "noch nichts erfasst",
        noContexts:
          "Noch kein Geltungskontext erfasst. Ohne ihn nennt der Export, was die Extraktion zur Geltung gelesen hat.",
        institution: "Einrichtung: {text}",
        targetGroup: "Zielgruppe: {text}",
        range: "{from} bis {to}",
        span: "{kind} {from}–{to}",
        spanFrom: "{kind} ab {from}",
        spanTo: "{kind} bis {to}",
        amount: "{amount} {unit}",
        amountRange: "{from}–{to} {unit}",
        recommended: "{value}, Empfehlung",
        whole: "{value} insgesamt",
        // a stored value with its review status (cv:ReviewStatuses), as the tree says it
        withStatus: "{value} ({status})",
        emptyContext: "ohne Angaben",
        // between the parts of a context or the values of a holder, and between the variants of a specification
        separator: " · ",
        listSeparator: ", ",
        // the title and field of one specification (SpecificationForm.vue)
        formHeading: "Titel und Fach von „{title}“",
        title: "Titel",
        titleHint: "Pflichtfeld. Wie das Dokument die Spezifikation nennt: Fach, Beruf, Studiengang oder Kurs.",
        fieldText: "Fach",
        fieldTextHint:
          "Fach oder Feld im Wortlaut des Dokuments. Ein Lehrplan ohne Fach bekommt in der Prüfung einen Hinweis.",
        save: "Titel und Fach speichern",
        // the button's name for a screen reader, its visible words first (WCAG 2.5.3): which specification it saves
        saveNamed: "Titel und Fach speichern: {title}",
        saved: "Gespeichert.",
        unchanged: "Nichts geändert.",
        saveFailed: "Titel und Fach wurden nicht gespeichert.",
        changedMeanwhile: "Jemand hat die Spezifikation inzwischen geändert; der neue Stand ist geladen.",
        fieldProblem: "{field}: {problem}",
        // a specification's values and contexts in their form (ValueSection.vue): named for it, under its title
        valuesHeading: "Niveau, Zeit, Umfang und Geltung von „{title}“",
        // the button's name for a screen reader, its visible words first (WCAG 2.5.3)
        valuesSaveNamed: "Werte speichern: {title}",
        gone: "Diese Spezifikation gibt es nicht mehr; die Geltung wird neu geladen.",
        // leaving the page with a draft of a specification's title, field, values or contexts (DocumentView.vue)
        leave: {
          title: "Änderungen verwerfen?",
          message: "Deine Änderungen an der Geltung sind nicht gespeichert. Gehst du weiter, gehen sie verloren.",
          confirm: "Verwerfen",
          cancel: "Weiter bearbeiten",
        },
        // the values' form did not come: what the section shows stays, editing waits for it
        formFailed: "Niveau, Zeit, Umfang und Geltung lassen sich gerade nicht bearbeiten: Das Formular dazu wurde nicht geladen.",
      },
      // a document's rules (DocumentRules.vue, RuleForm.vue, RuleNew.vue; backend app/api/rules.py)
      rules: {
        heading: "Regeln",
        intro:
          "Was das Dokument zur Auswahl, zu Voraussetzungen, zum Abschluss, zur Anrechnung und zum Verlauf vorgibt – " +
          "im Wortlaut, mit den Werten daraus und dem, wofür die Regel gilt.",
        loading: "Die Regeln werden geladen …",
        loadFailed: "Die Regeln wurden nicht geladen.",
        noneTitle: "Keine Regeln",
        noneBody: "Die Extraktion hat in diesem Dokument keine Regel gelesen. Du kannst eine anlegen.",
        noneBodyReadOnly: "Die Extraktion hat in diesem Dokument keine Regel gelesen.",
        closed: {
          frozen: "Das Dokument ist festgeschrieben: Die Regeln sind nur zu lesen.",
          job_open: "Zu diesem Dokument läuft gerade ein Auftrag: Die Regeln sind bis zu seinem Ende nur zu lesen.",
          not_extracted: "Die Extraktion hat noch nicht jedes Arbeitspaket gelesen: Die Regeln sind bis dahin nur zu lesen.",
        },
        readOnly: "Die Regeln ändern die Eigentümerin oder der Eigentümer des Dokuments und die Redaktion.",
        // cur:Rule's kinds by X3's ruleKind
        kinds: {
          selection: "Auswahlregel",
          prerequisite: "Voraussetzungsregel",
          completion: "Abschlussregel",
          recognition: "Anrechnungsregel",
          progression: "Fortschrittsregel",
        },
        // the facts of a rule
        verbatim: "Wortlaut",
        values: "Werte",
        optionTexts: "Optionen im Wortlaut",
        appliesTo: "Gilt für",
        options: "Optionen",
        requires: "Verlangt",
        anchors: "Fundstelle",
        status: "Prüfstand",
        none: "keine",
        count: "Anzahl: {bounds}",
        amount: "Umfang: {bounds} {unit}",
        requirement: "Voraussetzung: {kind}",
        share: "Höchstanteil: {share} %",
        between: "{least} bis {most}",
        atLeast: "mindestens {value}",
        atMost: "höchstens {value}",
        unnamed: "{kind} ohne Namen",
        separator: " · ",
        listSeparator: ", ",
        // a selection of fewer than two linked options: the export names no kind until two are linked
        unlinked:
          "Diese Auswahlregel hat weniger als zwei verknüpfte Optionen. Verknüpfe mindestens zwei, damit der Export " +
          "sie als Auswahlregel nennt.",
        // what a button names a rule by: its kind and the start of its wording
        named: "{kind} „{wording}“",
        edit: "Regel bearbeiten",
        editNamed: "Regel bearbeiten: {rule}",
        close: "Schließen",
        // the rows a rule names in one role (RuleTargets.vue)
        noneChosen: "Noch nichts gewählt.",
        search: "Suchen",
        moreMatch: "{count} {count|weiterer passt|weitere passen}; grenze die Suche ein.",
        noMatch: "Nichts passt zur Suche.",
        chosenSaid: "Du hast „{label}“ gewählt.",
        releasedSaid: "Du hast „{label}“ entfernt.",
        // closing a rule's form over a draft (RuleForm.vue)
        discardTitle: "Änderungen an der Regel verwerfen?",
        discardMessage: "Deine Änderungen an dieser Regel sind nicht gespeichert. Schließt du das Formular, gehen sie verloren.",
        discardConfirm: "Verwerfen",
        discardCancel: "Weiter bearbeiten",
        // a rule's form (RuleForm.vue)
        formHeading: "{kind} bearbeiten",
        fields: {
          kind: "Art",
          verbatim: "Wortlaut",
          min_count: "Mindestanzahl",
          max_count: "Höchstanzahl",
          min_amount: "Mindestumfang",
          max_amount: "Höchstumfang",
          amount_unit: "Einheit des Umfangs",
          requirement_kind: "Art der Voraussetzung",
          max_share: "Höchstanteil (0 bis 1)",
          option_texts: "Optionen im Wortlaut, eine je Zeile",
          applies_to: "Gilt für",
          options: "Optionen",
          requires: "Verlangt",
          page: "Seite der Fundstelle",
        },
        kindHint:
          "Optionen trägt nur eine Auswahlregel, Verlangtes und die Art der Voraussetzung nur eine " +
          "Voraussetzungsregel, einen Höchstanteil nur eine Anrechnungsregel; mit einer anderen Art gehen sie beim Speichern.",
        save: "Regel speichern",
        // the button's name for a screen reader, its visible words first (WCAG 2.5.3): which rule it saves
        saveNamed: "Regel speichern: {rule}",
        saved: "Gespeichert.",
        unchanged: "Nichts geändert.",
        saveFailed: "Die Regel wurde nicht gespeichert.",
        changedMeanwhile: "Jemand hat die Regel inzwischen geändert; der neue Stand ist geladen.",
        fieldProblem: "{field}: {problem}",
        gone: "Diese Regel gibt es nicht mehr; die Regeln werden neu geladen.",
        // taking a rule away: a run's is rejected and stays, an editor's own is deleted
        reject: "Regel verwerfen",
        rejectNamed: "Regel verwerfen: {rule}",
        delete: "Regel löschen",
        deleteNamed: "Regel löschen: {rule}",
        rejectTitle: "Regel verwerfen?",
        rejectMessage: "Die Regel bleibt als verworfen stehen und geht nicht mehr in den Export.",
        deleteTitle: "Regel löschen?",
        deleteMessage: "Die Regel hast du oder die Redaktion von Hand angelegt; sie wird mit ihren Befunden gelöscht.",
        rejected: "Die Regel ist verworfen.",
        deleted: "Die Regel ist gelöscht.",
        takeFailed: "Die Regel wurde nicht weggenommen.",
        // a new rule (RuleNew.vue)
        add: "Regel anlegen",
        newHeading: "Neue Regel",
        pageHint: "Pflichtfeld. Die Seite der Datei, auf der die Regel steht.",
        create: "Anlegen",
        cancel: "Abbrechen",
        created: "Die Regel ist angelegt.",
        createFailed: "Die Regel wurde nicht angelegt.",
        problems: {
          not_count: "Hier gehört eine ganze Zahl ab 0 hin.",
          not_share: "Hier gehört eine Zahl von 0 bis 1 hin, etwa 0,5.",
          not_page: "Hier gehört eine Seite der Datei hin, ab 1.",
        },
        // leaving the page with a draft of a rule (DocumentView.vue)
        leave: "Deine Änderungen an den Regeln sind nicht gespeichert. Gehst du weiter, gehen sie verloren.",
      },
      // a document's assessments (plan M3a J; DocumentAssessments.vue, AssessmentItem.vue, AssessmentForm.vue)
      assessments: {
        heading: "Prüfungen",
        intro:
          "Prüfungen, ihre Teile und Bereiche, Modulprüfungen und Studienleistungen des Dokuments: woran sie hängen, " +
          "wie lange sie dauern, wie sie gewichtet und benotet sind und was sie prüfen.",
        loading: "Die Prüfungen werden geladen …",
        loadFailed: "Die Prüfungen wurden nicht geladen.",
        noneTitle: "Noch keine Prüfung",
        noneBody: "Das Dokument nennt noch keine Prüfung.",
        noneBodyEditable: "Lege eine Prüfung an, wenn das Dokument eine vorsieht.",
        closed: {
          frozen: "Das Dokument ist festgeschrieben: Die Prüfungen sind nur zu lesen.",
          job_open: "Zu diesem Dokument läuft gerade ein Auftrag: Die Prüfungen sind bis zu seinem Ende nur zu lesen.",
          not_extracted: "Die Extraktion hat noch nicht jedes Arbeitspaket gelesen: Die Prüfungen sind bis dahin nur zu lesen.",
        },
        readOnly: "Prüfungen ändern die Eigentümerin oder der Eigentümer des Dokuments und die Redaktion.",
        unnamed: "Prüfung ohne Namen",
        // what an assessment states, in words (assessmentWords.ts)
        kind: "Art",
        parent: "Teil von",
        duration: "Dauer",
        weight: "Gewicht",
        graded: "Benotet",
        targets: "Prüft",
        levels: "Niveaus",
        minutes: "{minutes} {minutes|Minute|Minuten}",
        percent: "{weight} %",
        yes: "ja",
        no: "nein",
        none: "nicht angegeben",
        noTargets: "nichts verknüpft",
        noLevels: "keine",
        separator: ", ",
        // the list of an assessment's parts, for a screen reader
        parts: "Teile von „{title}“",
        // the ways on from an assessment, their names for a screen reader with the visible words first (WCAG 2.5.3)
        add: "Prüfung anlegen",
        addPart: "Teil anlegen",
        addPartNamed: "Teil anlegen: {title}",
        edit: "Bearbeiten",
        editNamed: "Bearbeiten: {title}",
        drop: "Entfernen",
        dropNamed: "Entfernen: {title}",
        dropTitle: "Prüfung entfernen?",
        dropMessage:
          "„{title}“ geht mit {parts} {parts|Teil|Teilen}, ihren Niveaus und den Befunden daran verloren. " +
          "Das lässt sich nicht rückgängig machen.",
        dropConfirm: "Entfernen",
        dropped: "„{title}“ ist entfernt.",
        dropFailed: "Die Prüfung wurde nicht entfernt.",
        gone: "Diese Prüfung gibt es nicht mehr; die Prüfungen werden neu geladen.",
        // the form of one assessment, new or kept (AssessmentForm.vue)
        addHeading: "Neue Prüfung",
        addPartHeading: "Neuer Teil von „{title}“",
        editHeading: "„{title}“ bearbeiten",
        fields: {
          parent_id: "Teil von (Pflichtfeld)",
          assessment_kind: "Art (Pflichtfeld)",
          label: "Name",
          duration_minutes: "Dauer in Minuten",
          weight_percent: "Gewicht in Prozent",
          graded: "Benotet",
          targets: "Prüft",
        },
        hints: {
          parent_id: "Die Spezifikation, der Abschnitt der Gliederung oder die Prüfung, deren Teil sie ist.",
          assessment_kind: "Die Art aus der Liste der Prüfungsarten.",
          label: "Wie das Dokument sie nennt, etwa „Abschlussprüfung Teil 1“.",
          duration_minutes: "Eine ganze Zahl, wie das Dokument sie nennt.",
          weight_percent: "Der Anteil an der Prüfung, deren Teil sie ist: eine Zahl von 0 bis 100, etwa 37,5.",
          graded: "Ob das Dokument eine Note für sie vorsieht.",
          targets: "Die Abschnitte der Gliederung, die sie prüft.",
        },
        choose: "Bitte wählen",
        groups: { specification: "Spezifikationen", node: "Gliederung", assessment: "Prüfungen" },
        gradedUnknown: "nicht angegeben",
        noChoices: "Die Gliederung hat noch keinen Abschnitt.",
        problems: {
          not_whole: "Hier gehört eine ganze Zahl ab 0 hin.",
          not_weight: "Hier gehört eine Zahl von 0 bis 100 hin, etwa 37,5.",
          too_many_targets: "Wähle höchstens {most} {most|Abschnitt|Abschnitte}.",
        },
        // a kind the assessment keeps though the list offers it no more
        retiredKind: "{kind} (wird nicht mehr angeboten)",
        save: "Speichern",
        saveNamed: "Speichern: {title}",
        cancel: "Abbrechen",
        added: "Angelegt.",
        saved: "Gespeichert.",
        unchanged: "Nichts geändert.",
        saveFailed: "Die Prüfung wurde nicht gespeichert.",
        changedMeanwhile: "Jemand hat die Prüfung inzwischen geändert; der neue Stand ist geladen.",
        fieldProblem: "{field}: {problem}",
        // the levels at one assessment in their form (ValueSection.vue)
        levelsHeading: "Niveaus von „{title}“",
        // the button's name for a screen reader, its visible words first (WCAG 2.5.3)
        levelsSaveNamed: "Werte speichern: {title}",
        formFailed: "Die Niveaus lassen sich gerade nicht bearbeiten: Das Formular dazu wurde nicht geladen.",
        // leaving the page with a draft of an assessment or of its levels (DocumentView.vue)
        leave: "Deine Änderungen an den Prüfungen sind nicht gespeichert. Gehst du weiter, gehen sie verloren.",
      },
      // the frozen document's export as Curriculum-Kern RDF (DocumentKernExport.vue)
      kernExport: {
        heading: "Export als Curriculum-Kern",
        contains:
          "Die Datei beschreibt das festgeschriebene Dokument als RDF nach dem Curriculum-Kern (Turtle), unter " +
          "den IRIs, die es beim Festschreiben bekam: Werk, Fassung und Revision, Knoten, Aussagen und ihre " +
          "Fundstellen. Sie nennt die Quelle und den Rechtestatus der Wortlaute; ein Import dazu den Plan von " +
          "MEM-Schule, die Namensnennung und, wo eingetragen, die Lizenz der Daten.",
        button: "Als Curriculum-Kern exportieren",
        working: "Der Export wird erstellt; das kann bis zu einer Minute dauern.",
        saved: "Die Datei {name} wurde dem Browser zum Speichern übergeben.",
        savedAccepted:
          "Die Datei {name} wurde dem Browser zum Speichern übergeben. Beim Festschreiben " +
          "{count|wurde|wurden} {count} {count|Verstoß|Verstöße} angenommen; der Kopf der Datei nennt die Zahl.",
        failed: "Der Export ließ sich nicht erstellen.",
        wait: "Versuch es in {count} {count|Sekunde|Sekunden} erneut.",
        again: "Versuch es gleich noch einmal.",
        saveFailed: "Die Datei wurde erstellt, ließ sich aber nicht an den Browser übergeben. Versuch es noch einmal.",
      },
      // its title, issuer and edition and its work (documentMeta.ts, DocumentEdition.vue)
      edition: {
        // the section (DocumentEdition.vue)
        heading: "Werk und Fassung",
        iri: "IRI",
        revision: "Revision",
        none: "nicht angegeben",
        noIri: "noch keine; sie entsteht beim Festschreiben",
        saveFailed: "Die Angaben wurden nicht gespeichert.",
        workFailed: "Das Werk wurde nicht gesetzt.",
        // the title, issuer and edition (DocumentMetaForm.vue)
        metaHeading: "Titel, Herausgeber und Fassung",
        title: "Titel",
        titleHint: "Wie der Lehrplan sich selbst nennt.",
        issuer: "Herausgeber",
        issuerHint: "Wer den Lehrplan herausgibt, etwa das Ministerium. Daraus entsteht beim Festschreiben die IRI.",
        edition: "Fassung",
        editionHint: "Welche Fassung, etwa das Jahr oder die Auflage. Auch sie geht in die IRI ein.",
        named: "Das Dokument hat seine IRI: Herausgeber und Fassung bleiben, wie sie sind.",
        save: "Angaben speichern",
        saved: "Gespeichert.",
        unchanged: "Nichts geändert.",
        // a field's problem said where the keyboard stayed elsewhere (DocumentMetaForm.vue, WorkForm.vue)
        fieldProblem: "{field}: {problem}",
        // the work (WorkForm.vue)
        workHeading: "Werk",
        workIntro:
          "Das Werk fasst die Fassungen eines Lehrplans zusammen. Sein Land und sein Kurztitel gehen in die IRI des " +
          "Werks und des Dokuments ein.",
        worksLoading: "Die bekannten Werke werden geladen …",
        worksFailed: "Die bekannten Werke wurden nicht geladen; ein neues lässt sich trotzdem anlegen.",
        workNone: "Noch ist kein Werk bekannt: Lege das erste an.",
        workWhich: "Welches Werk?",
        workExisting: "Ein bekanntes Werk",
        workNew: "Ein neues Werk",
        workChosen: "Bekanntes Werk",
        workChoosePlaceholder: "Werk wählen …",
        workChoose: "Wähle ein Werk.",
        workTitle: "Titel des Werks",
        workRegion: "Land des Werks",
        workRegionPlaceholder: "Land wählen …",
        workRegionChoose: "Wähle das Land des Werks.",
        workShortTitle: "Kurztitel",
        workShortTitleHint:
          "Kleinbuchstaben und Ziffern, Wörter mit einem Bindestrich verbunden, etwa „klp-physik“: der letzte Teil " +
          "der IRI des Werks.",
        workShortTitleBad:
          "Der Kurztitel braucht Kleinbuchstaben oder Ziffern, Wörter mit je einem Bindestrich verbunden – ohne " +
          "Umlaute, Leerzeichen und Bindestrich am Anfang oder Ende.",
        workSave: "Werk setzen",
        workSaved: "Werk gesetzt.",
        // the edition it supersedes (SupersedesForm.vue; the fact in DocumentEdition.vue)
        supersedes: "Ersetzt",
        supersedesHeading: "Ersetzte Fassung",
        supersedesIntro:
          "Ersetzt dieses Dokument eine frühere Fassung desselben Werks, steht das im Kern-Graphen. Zur Wahl stehen " +
          "die festgeschriebenen Fassungen des Werks unter einer anderen IRI.",
        supersedesLoading: "Die Fassungen des Werks werden geladen …",
        supersedesLoadFailed: "Die Fassungen des Werks wurden nicht geladen.",
        supersedesNone:
          "Von diesem Werk ist keine andere Fassung festgeschrieben, die du lesen darfst: Es gibt nichts zu ersetzen.",
        supersedesNoWork: "Ersetzen lässt sich nur eine Fassung desselben Werks: Erst braucht das Dokument sein Werk.",
        supersedesChosen: "Ersetzte Fassung",
        supersedesNothing: "keine",
        supersedesOption: "{edition} ({iri})",
        supersedesSave: "Ersetzte Fassung speichern",
        supersedesSaved: "Gespeichert.",
        supersedesFailed: "Die ersetzte Fassung wurde nicht gespeichert.",
      },
      // where the document comes from: its entry's provenance and fetching (DocumentSource.vue)
      source: {
        heading: "Herkunft",
        loading: "Die Herkunft wird geladen.",
        hidden: "Den Registereintrag dieses Dokuments sieht dein Konto nicht.",
        failed: "Die Herkunft wurde nicht geladen.",
      },
      // the revisions of the document's IRI (RevisionList.vue)
      revisions: {
        heading: "Revisionen dieser IRI",
        frozen: "Revision {revision}, festgeschrieben am {date}",
        draft: "Revision {revision}, Entwurf",
        failed: "Die Revisionen dieser IRI wurden nicht geladen.",
      },
      // the document's revision: frozen and copied (documentRevision.ts, RevisionNotice.vue)
      revision: {
        frozen: "Festgeschrieben am {date}, Revision {revision}.",
        frozenText: "Baum, Angaben und Werk bleiben, wie sie sind; weiter geht es in einer Entwurfskopie.",
        iri: "IRI: {iri}",
        // said where the keyboard was elsewhere as the document was frozen (DocumentView.vue)
        frozenSaid: "Das Dokument ist festgeschrieben.",
        copy: "Als Entwurf kopieren",
        copyFailed: "Die Entwurfskopie wurde nicht angelegt.",
        toDraft: "Zum offenen Entwurf",
        draft: "Entwurfskopie von Revision {revision}.",
        draftText: "Bearbeite und prüfe sie, dann schreibe sie fest; bis dahin gilt die festgeschriebene Fassung.",
        toOriginal: "Zur festgeschriebenen Fassung",
        copied: "Entwurfskopie angelegt.",
      },
      runs: "Läufe der Stufen",
      runsTable: "Tabelle der Läufe",
      noRuns: "Noch keine Läufe.",
      columns: {
        stage: "Stufe",
        attempt: "Versuch",
        state: "Stand",
        started: "Beginn",
        finished: "Ende",
        failure: "Grund",
      },
    },
    list: {
      heading: "Dokumente",
      untitled: "Dokument ohne Titel vom {made}",
      empty: "Aus diesem Eintrag ist noch kein Dokument angelegt.",
      // a document imported from a MEM plan rather than extracted (SourceDocuments.vue)
      imported: "Import aus MEM-Schule",
      loadFailed: "Die Dokumente wurden nicht geladen.",
    },
    tree: {
      loadFailed: "Der Baum des Dokuments wurde nicht geladen.",
      heading: "Baum: {title}",
      back: "Zum Dokument",
      treeHeading: "Knoten und Aussagen",
      // ways between the row chosen, its panel and the source on a long page (DocumentTreeView.vue)
      jump: {
        toPanel: "Zur Auswahl",
        toRow: "Zurück zur Zeile im Baum",
        toSource: "Zur Quelle",
        // "toRow" pressed while the status filter hides the row chosen
        rowFiltered: "Die gewählte Zeile ist durch den Filter ausgeblendet.",
      },
      detail: {
        heading: "Auswahl",
        none: "Wähle im Baum eine Zeile: Hier stehen dann ihre Felder und Fundstellen, darunter ihre Stelle in der Quelle.",
        node: "Knoten {name}",
        statement: "Aussage",
      },
      label: "Knoten und Aussagen des Dokuments",
      untitled: "ohne Titel",
      // what a row is, said to a screen reader before its label (treeRowWords.ts)
      kinds: { node: "Knoten", statement: "Aussage" },
      findings: "{count} {count|Befund|Befunde}",
      matching: "{count} {count|Zeile passt|Zeilen passen} zum Filter.",
      noMatch: "Keine Zeile passt zum Filter.",
      empty: {
        title: "Noch keine Knoten",
        body: "Die Extraktion hat in diesem Dokument noch keinen Knoten angelegt.",
      },
      // the form's fields by their keys (backend app/vocab/forms.py)
      fields: {
        original_title: "Titel",
        function: "Funktion",
        node_type: "Knotentyp",
        code: "Code",
        obligation: "Verbindlichkeit",
        verbatim: "Wortlaut",
        lead_in: "Einleitungssatz",
        statement_kind: "Art der Aussage",
        subkind: "Unterart",
        addressees: "Adressaten",
        // not a field of the form: a statement's anchors in its draft (anchorDraft.ts)
        anchors: "Fundstellen",
        codeText: "Code im Wortlaut",
        levelText: "Niveau im Wortlaut",
        timeText: "Zeit im Wortlaut",
        contextText: "Kontext im Wortlaut",
        referenceMarker: "Verweis im Wortlaut",
        exampleText: "Beispiel im Wortlaut",
        purposeText: "Zweck im Wortlaut",
      },
      // cv:Origins by notation without its "orig_" (RowDetail.vue)
      origins: {
        source: "aus der Quelle",
        inherited: "vererbt",
        rule: "per Regel",
        model: "vom Modell",
        human: "redaktionell",
        official: "amtlich",
        import: "aus einem Datensatz übernommen",
      },
      facts: { origin: "Herkunft", status: "Prüfstand", revision: "Revision", iri: "IRI" },
      source: {
        heading: "Quelle",
        page: "Seite {page} von {pages}",
        printedPage: "Seite {page} von {pages} (gedruckt {printed})",
        citedNote: "Mit „Beleg“ markiert: die Blöcke, die die gewählte Zeile nennt.",
        loadFailed: "Die Quelle wurde nicht geladen.",
        // choosing a statement's anchor in the source (BlockList.vue, SourcePane.vue)
        pick: "Block {id} als Fundstelle wählen",
        pickLabel: "Als Fundstelle wählen",
        pickNote: "Wähle die Blöcke, in denen die Aussage steht, und übernimm sie als Fundstelle.",
        take: "{count|Gewählten Block|Gewählte Blöcke} als Fundstelle übernehmen ({count})",
        notFound: "Seite {page} als „nicht gefunden“ übernehmen",
        // how an anchor taken went (AnchorTaking)
        taken: "Fundstelle übernommen – {anchor}.",
        held: "Diese Fundstelle steht schon im Entwurf – {anchor}.",
        refused: "Der Entwurf nimmt keine Fundstelle mehr an; er lässt sich nicht mehr speichern.",
      },
      notGiven: "nicht angegeben",
      assignedCode: "{code} (aus der Position vergeben)",
      // the row's form (FormFieldInput.vue, RowForm.vue)
      form: {
        choose: "Bitte wählen",
        none: "keine Angabe",
        unknownValue: "unbekannt: {iri}",
        save: "Änderungen speichern",
        saveFailed: "Die Änderung wurde nicht gespeichert.",
        saved: "Gespeichert.",
        unchanged: "Nichts geändert, nichts zu speichern.",
        closedLabel: "Nicht gespeichert",
        keptDraft: "Dein Entwurf, zum Abschreiben – er wurde nicht gespeichert:",
      },
      // a field's problem by the server's word for it (invalid_field details.problem; rowSave.ts)
      problems: {
        unknown: "Dieses Feld kennt das Formular nicht.",
        required: "Dieses Feld braucht einen Wert.",
        not_text: "Hier gehört ein Text hin.",
        not_list: "Hier gehört eine Auswahl von Werten hin.",
        too_long: "Der Text ist länger, als dieses Feld erlaubt.",
        not_storable: "Der Text enthält Zeichen, die sich nicht speichern lassen.",
        not_offered: "Diesen Wert bietet die Auswahlliste nicht an.",
        not_under: "Dieser Wert passt nicht zur gewählten Funktion oder Art.",
        unknown_block: "Ein gewählter Block steht nicht in der Umwandlung; entferne die Fundstelle und wähle neu.",
        no_page: "Eine gewählte Seite gibt es in der Datei nicht; entferne die Fundstelle und wähle eine andere.",
        // a set of values (backend app/vocab/value_checks.py, app/api/values.py)
        not_held: "Einen Wert dieser Art trägt diese Zeile nicht.",
        out_of_order: "Das Ende des Bereichs liegt vor seinem Anfang.",
        unknown_value: "Diesen Wert gibt es an dieser Zeile nicht mehr; lade die Zeile neu.",
        refused: "Die Datenbank hat diesen Wert abgewiesen; prüfe die Angaben.",
        // an assessment's parent among its own parts (backend app/db/assessments.py)
        cycle: "Eine Prüfung kann nicht Teil eines ihrer eigenen Teile sein.",
        other: "Dieser Wert lässt sich so nicht speichern.",
        elsewhere: "Ein Feld, das dieses Formular nicht zeigt, lässt sich so nicht setzen.",
      },
      // adding a row (rowCreate.ts, RowCreator.vue)
      create: {
        failed: "Die Zeile wurde nicht angelegt.",
        save: "Anlegen",
        cancel: "Abbrechen",
        created: "Angelegt.",
        // the ways on from a row chosen (RowActions.vue), and at the tree's top (DocumentTreeView.vue)
        child: "Unterknoten anlegen",
        statement: "Aussage anlegen",
        node: "Knoten anlegen",
        headingTop: "Neuer Knoten auf oberster Ebene",
        headingChild: "Neuer Knoten unter {name}",
        headingStatement: "Neue Aussage zu {name}",
        parentGone: "Die Zeile, unter der du anlegen wolltest, gibt es nicht mehr; der Baum wird neu geladen.",
        discard: {
          title: "Neue Zeile verwerfen?",
          message: "Die Zeile ist noch nicht angelegt. Verwirfst du sie, gehen deine Eingaben verloren.",
          confirm: "Verwerfen",
          cancel: "Weiter eintragen",
        },
      },
      // the document's tree checked again (treeCheck.ts, TreeTools.vue)
      check: {
        button: "Erneut prüfen",
        failed: "Die Prüfung wurde nicht gestartet.",
        lost: "Die Prüfung läuft im Konto des Eigentümers; lies den Baum neu, wenn sie fertig ist.",
        readAgain: "Baum neu lesen",
        running: "Die Prüfung läuft noch.",
        done: "Die Prüfung ist fertig; der Baum ist neu gelesen.",
      },
      // a row's review status (rowReview.ts, ReviewToggles.vue)
      review: {
        label: "Prüfstand",
        set: "Prüfstand: {status}.",
        stale: "Die Zeile wurde inzwischen geändert; der Baum wird neu geladen. Setze den Prüfstand erneut.",
        failed: "Der Prüfstand wurde nicht gesetzt.",
      },
      // taking a row away (rowDrop.ts, RowActions.vue); dropped, deleted, rejected, stale by the outcome
      drop: {
        delete: "Löschen",
        reject: "Verwerfen",
        titleNode: "Knoten löschen?",
        titleReject: "Aussage verwerfen?",
        titleDelete: "Aussage löschen?",
        messageNode:
          "Der Knoten wird gelöscht – mit {under} {under|Unterknoten|Unterknoten}, {statements} {statements|Aussage|Aussagen} und ihren Befunden.",
        messageReject: "Die Aussage bleibt im Baum, als verworfen; ihr Prüfstand lässt sich zurücksetzen.",
        messageDelete: "Die von Hand angelegte Aussage wird gelöscht, mit ihren Fundstellen und Befunden.",
        dropped: "Gelöscht: der Knoten mit {under} {under|Unterknoten|Unterknoten} und {statements} {statements|Aussage|Aussagen}.",
        deleted: "Die Aussage ist gelöscht.",
        rejected: "Die Aussage ist verworfen; sie bleibt im Baum.",
        stale: "Die Zeile wurde inzwischen geändert; der Baum wird neu geladen. Prüfe sie, bevor du es noch einmal versuchst.",
        failed: "Die Zeile wurde nicht gelöscht.",
      },
      // why the tree only reads: the document's state (TreeOut.closed), else the caller's role (RowPanel.vue)
      closed: {
        frozen: "Das Dokument ist festgeschrieben; Änderungen gehen nur in einer Entwurfskopie.",
        job_open: "Zu diesem Dokument läuft gerade ein Auftrag; bearbeiten lässt es sich wieder, sobald er fertig ist.",
        not_extracted:
          "Die Extraktion hat noch nicht jedes Arbeitspaket gelesen, oder der Import aus MEM-Schule hat seinen " +
          "Baum noch nicht geschrieben; bearbeiten lässt es sich danach.",
        noRole: "Bearbeiten dürfen der Eigentümer und die Redaktion.",
      },
      gone: "Diese Zeile gibt es nicht mehr; der Baum wird neu geladen.",
      // a row a link or bookmark names that the tree does not hold (DocumentTreeView.vue)
      notHeld: "Die verlinkte Zeile steht nicht im Baum; sie wurde wohl entfernt.",
      // a draft asked about before it goes (DocumentTreeView.vue, leaveGuard.ts)
      leave: {
        title: "Änderungen verwerfen?",
        message: "Deine Änderungen an dieser Zeile sind nicht gespeichert. Gehst du weiter, gehen sie verloren.",
        confirm: "Verwerfen",
        cancel: "Weiter bearbeiten",
      },
      // a change laid beside the row as another stored it (ConflictPanel.vue)
      conflict: {
        heading: "Inzwischen gespeichert",
        intro:
          "Jemand hat diese Zeile geändert, während du sie bearbeitet hast. Entscheide bei jedem Feld unten, welcher Wert gilt, und speichere dann erneut.",
        introNothing:
          "Jemand hat diese Zeile geändert, während du sie bearbeitet hast. Diese Änderungen sind übernommen; speichere erneut, um deine dazuzulegen.",
        introAgain:
          "Jemand hat diese Zeile inzwischen gespeichert. Deine Änderungen sind noch nicht gespeichert; speichere erneut.",
        yours: "Dein Wert",
        stored: "Gespeichert",
        keep: "Meins behalten",
        take: "Gespeichertes nehmen",
        taken: "Übernommen, weil nur dort geändert:",
        empty: "leer",
        undecided: "Entscheide zuerst bei jedem Feld oben, welcher Wert gilt.",
      },
      anchors: {
        heading: "Fundstellen",
        none: "Keine Fundstelle.",
        where: "Seite",
        how: "Fundart",
        quote: "Zitat",
        blocks: "Blöcke",
        unchecked: "noch nicht geprüft",
        // cv:MatchKinds by notation (anchorWords.ts)
        matches: {
          exact: "wörtlich gefunden",
          whitespace: "bis auf Leerraum gefunden",
          elided: "mit Auslassung gefunden",
          normalized: "gefunden bis auf Trennstriche und Anführungszeichen",
          fuzzy: "nur unscharf gefunden, kein Wortlautbeleg",
          notFound: "nicht gefunden",
        },
        scored: "{found} (Übereinstimmung {score})",
        page: "Seite {page}",
        pages: "Seiten {first}–{last}",
        printed: "{pages} (gedruckt {printed})",
        noPage: "ohne Seite",
        show: "Seite {page} in der Quelle zeigen",
        // an anchor of a draft (anchorDraft.ts): blocks chosen in the source, or the page a passage stands on unfound
        draftBlocks: "{pages}: {count} {count|Block|Blöcke} ({ids})",
        draftPage: "Auf {pages} nicht gefunden",
        // the anchors of a statement's draft (AnchorDraftList.vue)
        draftHeading: "Fundstellen im Entwurf",
        draftNone: "Noch keine Fundstelle. Wähle in der Quelle die Blöcke, in denen die Aussage steht, und übernimm sie; steht sie in keinem, übernimm die Seite als nicht gefunden.",
        remove: "Entfernen",
      },
      // a row's levels, time spans and workloads (plan M3a G: valueWords.ts, valueDraft.ts, ValueSection.vue)
      values: {
        // a value's fields by their keys (backend app/vocab/value_forms.py)
        fields: {
          level: "Niveau",
          level_to: "Bis Niveau",
          relation: "Art der Zuordnung",
          dimension: "Niveaudimension",
          competence_dimension: "Kompetenzbereich",
          time_kind: "Art des Zeitraums",
          span_from: "Von",
          span_to: "Bis",
          time_relation: "Zeitbezug",
          amount: "Umfang",
          amount_to: "Bis",
          unit: "Einheit",
          workload_kind: "Art des Umfangs",
          is_recommendation: "Richtwert, nicht verbindlich",
          minutes_per_unit: "Minuten je Einheit",
          total: "Gesamtumfang",
          // a specification's applicability context's (ContextItemForm.vue)
          sector: "Bildungsbereich",
          formality: "Formalität",
          institution_text: "Einrichtung",
          target_group_text: "Zielgruppe",
        },
        heading: "Niveau, Zeit, Umfang",
        none: "Noch nichts erfasst.",
        // each kind, over its values and in a conflict (ValueSection.vue, ValueConflict.vue)
        kinds: { level_assignments: "Niveau", time_spans: "Zeitraum", workloads: "Umfang", contexts: "Geltungskontext" },
        add: {
          level_assignments: "Niveau hinzufügen",
          time_spans: "Zeitraum hinzufügen",
          workloads: "Umfang hinzufügen",
          contexts: "Geltungskontext hinzufügen",
        },
        // who stated a value, and how far it is reviewed
        stated: "{origin} · {status}",
        reviewLabel: "Prüfstand von „{value}“",
        // a value's review status set, told apart from the row's own (RowPanel.vue)
        reviewSet: "Prüfstand von „{value}“: {status}.",
        reviewStale: "Der Wert „{value}“ wurde inzwischen geändert und wird neu geladen. Setze den Prüfstand erneut.",
        reviewStaleContext:
          "Der Geltungskontext „{value}“ wurde inzwischen geändert und wird neu geladen. Setze den Prüfstand erneut.",
        // the most entries of a kind a holder takes (valueDraft.MOST_VALUES)
        most: "Mehr als {most} {most|Eintrag|Einträge} dieser Art werden nicht angenommen.",
        save: "Werte speichern",
        saving: "Die Werte werden gespeichert …",
        saveFailed: "Die Werte wurden nicht gespeichert.",
        // a set laid beside the values as another stored them (ValueConflict.vue)
        conflict: {
          intro:
            "Jemand hat diese Werte geändert, während du sie bearbeitet hast. Entscheide bei jeder Art unten, welcher Stand gilt, und speichere dann erneut.",
          introNothing:
            "Jemand hat diese Werte geändert, während du sie bearbeitet hast. Diese Änderungen sind übernommen; speichere erneut, um deine dazuzulegen.",
          introAgain:
            "Jemand hat inzwischen etwas gespeichert. Deine Werte sind noch nicht gespeichert; speichere erneut.",
          yours: "Dein Stand",
          empty: "keine",
        },
        // an entry of the values' form (ValueItemForm.vue): by its kind and place
        entry: {
          level_assignments: "Niveau {place}",
          time_spans: "Zeitraum {place}",
          workloads: "Umfang {place}",
          contexts: "Geltungskontext {place}",
        },
        // a problem the store found with a context as a whole, named by the context (ContextItemForm.vue)
        contextProblem: "{entry}: {problem}",
        // a field or a kind of values within a context, as a problem there is said (ValueSection.vue)
        inContext: "{context}, {field}",
        // what the store refused at a context as a whole (backend `refused` at `contexts[0]`)
        contextRefused: "Die Datenbank hat diesen Geltungskontext abgewiesen; prüfe seine Angaben.",
        remove: "{entry} entfernen",
        periodsKept: "Zeiträume dieses Umfangs: {spans}. Sie bleiben beim Speichern, wie sie sind.",
        // a value in words (valueWords.ts)
        words: {
          levelRange: "{from} bis {to}",
          numberRange: "{from}–{to}",
          span: "{kind} {span}",
          spanFrom: "{kind} ab {from}",
          spanTo: "{kind} bis {to}",
          amount: "{amount} {unit}",
          // a unit without a counted word below: by its label
          amountLabelled: "{unit}: {amount}",
          recommendation: "Richtwert",
          minutes: "je {minutes} {minutes|Minute|Minuten}",
          total: "Gesamtumfang",
          periods: "in {spans}",
        },
        // a workload's unit counted, by its notation in cv:WorkloadUnits; one not here is named by its label
        units: {
          lesson: "{count|Unterrichtsstunde|Unterrichtsstunden}",
          teachingUnit: "{count|Unterrichtseinheit|Unterrichtseinheiten}",
          hour: "{count|Zeitstunde|Zeitstunden}",
          weeklyLesson: "{count|Wochenstunde|Wochenstunden}",
          ectsCredit: "{count|ECTS-Leistungspunkt|ECTS-Leistungspunkte}",
          day: "{count|Tag|Tage}",
          week: "{count|Woche|Wochen}",
          month: "{count|Monat|Monate}",
          semester: "{count|Semester|Semester}",
          year: "{count|Jahr|Jahre}",
        },
        // a change of a statement refused at one of its levels (rowSave.ts): `level_assignments[0].level`
        heldInWay: "Das Niveau „{value}“ unter „Niveau, Zeit, Umfang“ steht dem entgegen; ändere oder entferne es zuerst. {problem}",
        // a number's problem, found before the set is sent (valueDraft.ts)
        problems: {
          not_number: "Hier gehört eine Zahl ab 0 hin, etwa 7,5.",
          not_whole: "Hier gehört eine ganze Zahl von 1 bis 2.147.483.647 hin.",
          too_many_digits: "Diese Zahl hat mehr als 15 Ziffern.",
        },
      },
      // cv:ReviewStatuses by notation without its "rev_" (reviewStatus.ts)
      statuses: { proposed: "Vorgeschlagen", confirmed: "Bestätigt", rejected: "Verworfen" },
      filter: {
        label: "Nach Prüfstand filtern",
        option: "{label}: {nodes} {nodes|Knoten|Knoten}, {statements} {statements|Aussage|Aussagen}",
        all: "Alle zeigen",
      },
    },
  },
} as const;

type Messages = typeof messages;

/** The locale the UI formats its numbers, plural forms and dates in. */
export const LOCALE = "de-DE";

/** A moment as the pages show it, date and time ("22.10.2026, 23:07"): one format wherever it shows. */
export const momentFormat = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });

/**
 * `{count|Abschnitt|Abschnitte}` - the noun in the form that agrees with
 * `count`. Per placeholder rather than per message, because one sentence can
 * hold two counts whose nouns agree with different ones.
 */
const PLURAL = /\{(\w+)\|([^|{}]*)\|([^|{}]*)\}/g;

const pluralRules = new Intl.PluralRules(LOCALE);
const numberFormat = new Intl.NumberFormat(LOCALE);

/** What a wording is filled with: counts, codes, names. */
export type MessageParams = Record<string, string | number | boolean>;

/** A wording, or a group of them, as the catalogue nests them. */
export interface Catalogue {
  readonly [name: string]: string | Catalogue;
}

/**
 * A parameter as the sentence shows it. A number of five digits and more is
 * grouped the German way ("125.000"), a fraction takes the decimal comma; four
 * digits stay as they are - how German prints them, and how a year reads.
 */
function display(value: string | number | boolean): string {
  if (typeof value !== "number") return String(value);
  return !Number.isInteger(value) || Math.abs(value) >= 10000 ? numberFormat.format(value) : String(value);
}

function applyPlurals(text: string, params: MessageParams): string {
  return text.replace(PLURAL, (match, name: string, one: string, other: string) => {
    const given = params[name];
    // A missing, blank or non-numeric count leaves the placeholder in plain
    // sight; picking a form would render confident nonsense. `Number("")` is 0,
    // not NaN, so a blank is ruled out by hand.
    if (given === undefined || given === "") return match;
    const count = Number(given);
    if (Number.isNaN(count)) return match;
    // Intl decides the category, so the rule stays the locale's.
    return pluralRules.select(count) === "one" ? one : other;
  });
}

/**
 * The wording at the dotted `key` in `catalogue`, filled with `params`; the key
 * itself where the catalogue holds no wording there, so a gap shows on screen.
 * Named placeholders keep sentences whole for translation instead of gluing
 * fragments together.
 */
export function translate(catalogue: Catalogue, key: string, params?: MessageParams): string {
  const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], catalogue);
  if (typeof value !== "string") return key;
  if (!params) return value;
  return applyPlurals(value, params).replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(params, name) ? display(params[name]) : match,
  );
}

/** The app's wording at `key`, e.g. t("login.errors.empty"). */
export function t(key: string, params?: MessageParams): string {
  return translate(messages, key, params);
}

export type { Messages };
