package com.plantoplate.model;

import jakarta.persistence.*;
import java.time.LocalDate;

@Entity
@Table(name = "users", uniqueConstraints = @UniqueConstraint(columnNames = "username"))
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String username;

    @Column(nullable = false)
    private String passwordHash;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Role role;

    @Column(nullable = false)
    private boolean isTempPassword;

    @Column(nullable = false)
    private boolean isDisabled;

    // Optional fields for tests
    private String firstName;
    private String lastName;
    private String email;
    private String phoneNumber;
    private String address;
    private String city;
    private String zipCode;
    private String state;
    private LocalDate dateOfBirth;

    // Getters
    public Long getId() { return id; }
    public String getUsername() { return username; }
    public String getPasswordHash() { return passwordHash; }
    public Role getRole() { return role; }
    public boolean getIsTempPassword() { return isTempPassword; }
    public boolean getIsDisabled() { return isDisabled; }
    public String getFirstName() { return firstName; }
    public String getLastName() { return lastName; }
    public String getEmail() { return email; }
    public String getPhoneNumber() { return phoneNumber; }
    public String getAddress() { return address; }
    public String getCity() { return city; }
    public String getZipCode() { return zipCode; }
    public String getState() { return state; }
    public LocalDate getDateOfBirth() { return dateOfBirth; }

    // Setters
    public void setId(Long id) { this.id = id; }
    public void setUsername(String username) { this.username = username; }
    public void setPasswordHash(String passwordHash) { this.passwordHash = passwordHash; }
    public void setRole(Role role) { this.role = role; }
    public void setIsTempPassword(boolean isTempPassword) { this.isTempPassword = isTempPassword; }
    public void setIsDisabled(boolean isDisabled) { this.isDisabled = isDisabled; }
    public void setFirstName(String firstName) { this.firstName = firstName; }
    public void setLastName(String lastName) { this.lastName = lastName; }
    public void setEmail(String email) { this.email = email; }
    public void setPhoneNumber(String phoneNumber) { this.phoneNumber = phoneNumber; }
    public void setAddress(String address) { this.address = address; }
    public void setCity(String city) { this.city = city; }
    public void setZipCode(String zipCode) { this.zipCode = zipCode; }
    public void setState(String state) { this.state = state; }
    public void setDateOfBirth(LocalDate dateOfBirth) { this.dateOfBirth = dateOfBirth; }

    // Constructors
    public User() {}

    public User(Long id, String username, String passwordHash, Role role, 
                 boolean isTempPassword, boolean isDisabled, 
                 String firstName, String lastName, String email,
                 String phoneNumber, String address, String city, 
                 String zipCode, String state, LocalDate dateOfBirth) {
        this.id = id;
        this.username = username;
        this.passwordHash = passwordHash;
        this.role = role;
        this.isTempPassword = isTempPassword;
        this.isDisabled = isDisabled;
        this.firstName = firstName;
        this.lastName = lastName;
        this.email = email;
        this.phoneNumber = phoneNumber;
        this.address = address;
        this.city = city;
        this.zipCode = zipCode;
        this.state = state;
        this.dateOfBirth = dateOfBirth;
    }
}
