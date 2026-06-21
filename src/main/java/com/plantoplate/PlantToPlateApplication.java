package com.plantoplate;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Main entry point for the PlanToPlate Spring Boot 3.x application.
 * 
 * Configuration:
 * - Java 21 LTS runtime (virtual threads enabled via application.yml)
 * - SQLite embedded database in WAL (Write-Ahead Logging) mode
 * - Hibernate with automatic schema update tracking
 */
@SpringBootApplication
public class PlantToPlateApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlantToPlateApplication.class, args);
    }
}
