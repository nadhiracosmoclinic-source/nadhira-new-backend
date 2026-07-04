CREATE DATABASE IF NOT EXISTS clinic CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE clinic;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('receptionist', 'doctor') NOT NULL,
    full_name VARCHAR(140) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    age INT NOT NULL,
    gender ENUM('Female', 'Male', 'Other') NOT NULL,
    phone VARCHAR(30) NOT NULL,
    date_of_visit DATE NOT NULL,
    location_area VARCHAR(180) NOT NULL,
    main_concern TEXT NOT NULL,
    created_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_patient_search (name, phone, patient_id),
    INDEX idx_patient_gender (gender),
    INDEX idx_visit_date (date_of_visit)
);

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

CREATE TABLE IF NOT EXISTS appointments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_db_id INT NOT NULL,
    appointment_date DATE NOT NULL,
    appointment_time VARCHAR(20) NOT NULL,
    doctor_name VARCHAR(120) DEFAULT 'Doctor',
    status ENUM('Scheduled', 'Completed', 'Cancelled') DEFAULT 'Scheduled',
    notes TEXT,
    created_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_db_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_appointment_date (appointment_date),
    INDEX idx_appointment_patient (patient_db_id)
);

CREATE TABLE IF NOT EXISTS prescriptions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prescription_no VARCHAR(40) NOT NULL UNIQUE,
    patient_db_id INT NOT NULL,
    prescription_date DATE NOT NULL,
    follow_up_date DATE,
    medicines JSON,
    skin_products JSON,
    hair_products JSON,
    session_recommended VARCHAR(140),
    session_type VARCHAR(180),
    treatment_notes TEXT,
    receptionist_instructions TEXT,
    created_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_db_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_prescription_date (prescription_date),
    INDEX idx_prescription_patient (patient_db_id)
);

CREATE TABLE IF NOT EXISTS product_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(220) NOT NULL,
    category ENUM('Medicine', 'Skin Care', 'Hair Care') NOT NULL DEFAULT 'Medicine',
    default_dose VARCHAR(120),
    default_notes VARCHAR(220),
    created_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_catalog_item (name, category),
    INDEX idx_catalog_name (name),
    INDEX idx_catalog_category (category)
);
