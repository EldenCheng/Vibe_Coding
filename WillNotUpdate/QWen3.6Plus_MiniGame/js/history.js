class History {
    constructor() {
        this.records = [];
        this.counter = 0;
    }

    addRecord(mode, result) {
        this.counter++;
        const record = {
            id: this.counter,
            mode: mode === 'pvp' ? '双人' : '人机',
            result: result
        };
        this.records.push(record);
        return record;
    }

    clear() {
        this.records = [];
        this.counter = 0;
    }

    getRecords() {
        return this.records;
    }
}

const history = new History();
