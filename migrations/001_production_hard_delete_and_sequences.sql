USE clinic;

DELIMITER //

CREATE PROCEDURE apply_nadhira_production_migration()
BEGIN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'patients' AND COLUMN_NAME = 'deleted_at'
    ) THEN
        ALTER TABLE patients DROP COLUMN deleted_at;
    END IF;

    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prescriptions' AND COLUMN_NAME = 'deleted_at'
    ) THEN
        ALTER TABLE prescriptions DROP COLUMN deleted_at;
    END IF;

    CREATE TABLE IF NOT EXISTS patient_id_sequences (
        sequence_date DATE PRIMARY KEY,
        next_number INT NOT NULL DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS prescription_sequences (
        sequence_date DATE PRIMARY KEY,
        next_number INT NOT NULL DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    );

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'appointments' AND INDEX_NAME = 'idx_appointment_patient'
    ) THEN
        CREATE INDEX idx_appointment_patient ON appointments (patient_db_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prescriptions' AND INDEX_NAME = 'idx_prescription_patient'
    ) THEN
        CREATE INDEX idx_prescription_patient ON prescriptions (patient_db_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'patients' AND INDEX_NAME = 'idx_patient_created'
    ) THEN
        CREATE INDEX idx_patient_created ON patients (created_at);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prescriptions' AND INDEX_NAME = 'idx_prescription_created'
    ) THEN
        CREATE INDEX idx_prescription_created ON prescriptions (created_at);
    END IF;
END//

DELIMITER ;

CALL apply_nadhira_production_migration();
DROP PROCEDURE apply_nadhira_production_migration;
