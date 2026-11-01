// Diekstrak dari app/templates/index.html: kamus & transliterasi Pegon sisi klien (cadangan)
    const CLIENT_PEGON_DICT = {
      "ari": "اَرِ", "eta": "ايتَا", "tetep": "تَتَڤْ", "saha": "سَاهَا", "naon": "نَاوُنْ",
      "kana": "كَانَا", "ka": "كَا", "ku": "كُو", "kalawan": "كَلَاوَانْ", "dina": "دِينَا",
      "di": "دِي", "tina": "تِينَا", "ti": "تِي", "nepi": "نَڤِي", "mangka": "مَڠْكَا",
      "geus": "ݢَوْسْ", "keur": "كَوْرْ", "baris": "بَارِسْ", "temen-temen": "تَمَنْ-تَمَنْ",
      "temen": "تَمَنْ", "terkadang": "تَرْكَادَاڠْ", "ampir-ampiran": "اَمْڤِيرْ-اَمْڤِيرَانْ",
      "ampir": "اَمْڤِيرْ", "yen": "يَينْ", "teh": "تَيْهْ", "ieu": "اِيئوُ", "itu": "اِيتُو",
      "anapon": "اَنَاڤَوْنْ", "boh": "بَوْهْ", "boh yen": "بَوْهْ يَيْـنْ",
      "henteu": "هِنْتَوْ", "aya": "اَيَا", "bukti": "بُوكْتِي", "halna": "حَالْنَا",
      "karana": "كَرَانَا", "lantaran": "لَنْتَارَانْ", "saestuna": "سَايَسْتُونَـا",
      "saenya-enyana": "سَاايڽَا-ايڽَانَا", "sakur": "سَاكُورْ", "puji": "ڤُوجِي",
      "gusti": "ݢُوسْتِي", "allah": "اَللَّهْ", "kabeh": "كَبَيهْ", "sadaya": "سَدَايَا",
      "kaula": "كَاوْلَا", "kuring": "كُورِڠْ", "anjeun": "اَنْجَوْنْ", "aranjeun": "اَرَانْجَوْنْ",
      "maraneh": "مَارَانَيهْ", "maranehna": "مَارَانَيهْنَا", "manehna": "مَانَيهْنَا",
      "jalma": "جَلْمَا", "jalma-jalma": "جَلْمَا-جَلْمَا", "pirang-pirang": "ڤِيرَاڠْ-ڤِيرَاڠْ",
      "perkara": "ڤَرْكَارَا", "anu": "اَنُو", "nu": "نُو", "nyusun": "ڽُوسُونْ",
      "kitab": "كِتَابْ", "opat": "اَوْڤَتْ", "bagean": "بَاݢَايَانْ", "saparapat": "سَاڤَارَاڤَتْ",
      "ibadah": "عِبَادَةْ", "adat": "عَادَةْ", "kabiasaan": "كَا بِيَاسَاءَانْ",
      "ngabinasakeun": "ڠَابِينَاسَاكَوْنْ", "nyalametkeun": "ڽَالَمَتْكَوْنْ",
      "kufur": "كُوفُورْ", "kafakiran": "كَافَاكِيرَانْ", "hate": "حَاتَي", "elmu": "عِلْمُو",
      "amal": "عَمَلْ", "luhureun": "لُوهُورَوْنْ", "handapeun": "هَنْدَاڤَوْنْ",
      "bagja": "بَاݢْجَا", "ariman": "اَرِيمَانْ", "iman": "اِيمَانْ", "islam": "اِسْلَامْ",
      "anging": "اَڠِيڠْ", "pastina": "ڤَسْتِينَا", "sakabeh": "سَكَابَيهْ", "niat": "نِيَّتْ",
      "pikeun": "ڤِيكَوْنْ", "unggal-unggal": "اوڠْݢَلْ-اوڠْݢَلْ", "hukumna": "حُكُومْنَا",
      "kageloan": "كَاݢَيلُوئَانْ", "make": "مَكَي", "dibarengan": "دِيبَارَيڠَانْ",
      "ayana": "اَيَانَا", "ngangkat": "ڠَاڠْكَتْ", "ngadawuh": "ڠَادَاوُوهْ", "ngucap": "ڠُوچَڤْ",
      "nyaho": "ڽَاهُو", "ningali": "نِيڠَالِي", "nangtung": "نَاڠْتُوڠْ"
    };

    const CLIENT_PEGON_CONS = {
      "ng": "ڠ", "ny": "ڽ", "ch": "چ", "kh": "خ", "gh": "غ", "sy": "ش",
      "sh": "ص", "dh": "ض", "th": "ط", "zh": "ظ", "b": "ب", "c": "چ",
      "d": "د", "f": "ف", "g": "ݢ", "h": "ه", "j": "ج", "k": "ك",
      "l": "ل", "m": "م", "n": "ن", "p": "ڤ", "q": "ق", "r": "ر",
      "s": "س", "t": "ت", "v": "ڤ", "w": "و", "y": "ي", "z": "ز"
    };

    function isArabicScript(text) {
      if (!text) return false;
      return /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/.test(text);
    }

    function transliteratePhoneticPegon(w) {
      if (!w) return "";
      let res = [];
      let i = 0;
      let n = w.length;
      let isStart = true;
      while (i < n) {
        if (i + 1 < n && w.slice(i, i+2) === "eu") {
          res.push(isStart ? "اَوْ" : "َوْ");
          i += 2; isStart = false; continue;
        } else if (i + 1 < n && w.slice(i, i+2) === "ai") {
          res.push(isStart ? "اَايْ" : "َايْ");
          i += 2; isStart = false; continue;
        } else if (i + 1 < n && w.slice(i, i+2) === "au") {
          res.push(isStart ? "اَاوْ" : "َاوْ");
          i += 2; isStart = false; continue;
        }

        const twoC = w.slice(i, i+2);
        if (i + 1 < n && CLIENT_PEGON_CONS[twoC]) {
          const c = CLIENT_PEGON_CONS[twoC];
          i += 2; isStart = false;
          if (i < n) {
            if (i + 1 < n && w.slice(i, i+2) === "eu") { res.push(c + "َوْ"); i += 2; }
            else if (w[i] === 'a') { res.push(c + "َا"); i += 1; }
            else if (w[i] === 'i') { res.push(c + "ِي"); i += 1; }
            else if (w[i] === 'u') { res.push(c + "ُو"); i += 1; }
            else if (w[i] === 'e' || w[i] === 'é') { res.push(c + "َيْ"); i += 1; }
            else if (w[i] === 'o') { res.push(c + "َاو"); i += 1; }
            else { res.push(c + "ْ"); }
          } else {
            res.push(c + "ْ");
          }
          continue;
        }

        const oneC = w[i];
        if (CLIENT_PEGON_CONS[oneC]) {
          const c = CLIENT_PEGON_CONS[oneC];
          i += 1; isStart = false;
          if (i < n) {
            if (i + 1 < n && w.slice(i, i+2) === "eu") { res.push(c + "َوْ"); i += 2; }
            else if (w[i] === 'a') { res.push(c + "َا"); i += 1; }
            else if (w[i] === 'i') { res.push(c + "ِي"); i += 1; }
            else if (w[i] === 'u') { res.push(c + "ُو"); i += 1; }
            else if (w[i] === 'e' || w[i] === 'é') { res.push(c + "َيْ"); i += 1; }
            else if (w[i] === 'o') { res.push(c + "َاو"); i += 1; }
            else { res.push(c + "ْ"); }
          } else {
            res.push(c + "ْ");
          }
          continue;
        }

        if (w[i] === 'a') res.push(isStart ? "اَ" : "َا");
        else if (w[i] === 'i') res.push(isStart ? "اِي" : "ِي");
        else if (w[i] === 'u') res.push(isStart ? "اُو" : "ُو");
        else if (w[i] === 'e' || w[i] === 'é') res.push(isStart ? "اَيْ" : "َيْ");
        else if (w[i] === 'o') res.push(isStart ? "اَوْ" : "َاو");
        else res.push(w[i]);
        i += 1; isStart = false;
      }
      return res.join('');
    }

    function sundaToPegonClient(text) {
      if (!text) return "";
      if (isArabicScript(text)) return text;
      const tokens = text.match(/[\w\-]+|[^\w\s]|\s+/g) || [];
      return tokens.map(tok => {
        if (/^\s+$/.test(tok)) return tok;
        if (/^[^\w\s]+$/.test(tok)) {
          if (tok === ',') return '،';
          if (tok === '?') return '؟';
          if (tok === ';') return '؛';
          return tok;
        }
        const low = tok.toLowerCase();
        if (CLIENT_PEGON_DICT[low]) return CLIENT_PEGON_DICT[low];
        if (low.includes('-')) {
          return low.split('-').map(part => CLIENT_PEGON_DICT[part] || transliteratePhoneticPegon(part)).join('-');
        }
        if (low.endsWith("na") && low.length > 3 && CLIENT_PEGON_DICT[low.slice(0, -2)]) {
          return CLIENT_PEGON_DICT[low.slice(0, -2)] + "نَا";
        }
        if (low.endsWith("keun") && low.length > 5 && CLIENT_PEGON_DICT[low.slice(0, -4)]) {
          return CLIENT_PEGON_DICT[low.slice(0, -4)] + "كَوْنْ";
        }
        return transliteratePhoneticPegon(low);
      }).join('');
    }
    function isArabicScript(text) {
      if (!text) return false;
      return /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/.test(text);
    }
