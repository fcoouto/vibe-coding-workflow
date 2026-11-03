async function drainInstructions({first, read, decode, emit}) {
    let packet = first, page = 1, revision = null, pages = null, batch = true, delivered = 0;
    while (true) {
        if (packet === null) {
            if (!batch) throw new Error("Instruction delivery incomplete: small-page output was omitted");
            // Keep the missing range and revision; do not replay delivered pages.
            batch = false;
            packet = decode(await read(page, revision, false), "instructions");
            if (packet === null) throw new Error("Instruction delivery incomplete: small-page output was omitted");
        }
        if (packet.page !== page || packet.batch !== batch ||
            (!batch && packet.last_page !== page) ||
            (revision !== null && packet.revision !== revision) ||
            (pages !== null && packet.pages !== pages)) {
            throw new Error("Instruction delivery incomplete: selection revision or page sequence changed");
        }
        revision = packet.revision;
        pages = packet.pages;
        await emit(packet.text);
        delivered++;
        if (packet.last_page === pages) return {complete: true, pages, batches: delivered, revision};
        page = packet.last_page + 1;
        packet = decode(await read(page, revision, batch), "instructions");
    }
}
