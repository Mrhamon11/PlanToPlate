-- Test database schema initialization for User entity

DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(600) NOT NULL,
    role VARCHAR(10) NOT NULL,
    is_temp_password BOOLEAN NOT NULL DEFAULT FALSE
);

-- Insert test users for authentication tests
INSERT INTO users (username, password_hash, role, is_temp_password) VALUES
('admin', '$2a$10$N.zmdr9k7uOCp4jczEY5eOS7xQNONqW6X.jlHhhLhZUJ38i9XUiBS', 'ADMIN', FALSE),  -- BCrypt hash of "testpassword"
('tempAdmin', '$2a$10$rO.vKz7r7uOCp4jczEY5eOS7xQNONqW6X.jlHhhLhZUJ38i9XUiBS', 'ADMIN', TRUE),  -- Temp password user
('regularUser', '$2a$10$rO.vKz7r7uOCp4jczEY5eOS7xQNONqW6X.jlHhhLhZUJ38i9XUiBS', 'USER', FALSE);
